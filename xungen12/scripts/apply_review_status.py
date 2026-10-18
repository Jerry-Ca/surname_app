#!/usr/bin/env python3
"""核对结果写库工具：按 CSV 更新证据状态，并在同一事务里写 review_logs（任务 C-09 的更新通道）。

import_data.py 是**只插入**的：编号重复就整批回滚。人工核对（核对台 / 逐条回看）做出的
「待核对 → 已核对」「→ 已撤回」决定没有地方落，手工 UPDATE 又会丢掉留痕。
这个脚本只做一件事：按 CSV 逐条 UPDATE evidences，并在**同一个事务**里把改前/改后写进
review_logs，留下可追责的人工核验记录。源自成员 B 2026-10-18 的提案
（`scripts/B/apply_review_status.py`，B→C 交接），C 收编进 `scripts/`，行为保持一致。

用法（项目目录下）：
    python3 scripts/apply_review_status.py data/incoming/<包>/review_B.csv            # 只预演，回滚
    python3 scripts/apply_review_status.py data/incoming/<包>/review_B.csv --apply    # 真正写入
    XUNGEN_DB=data/tmp/rehearsal.db python3 scripts/apply_review_status.py ...        # 先在副本上演练

约定：
  - CSV 列：evidence_id, verification_status, verified_by, verification_note
  - 状态必须来自 app/schema.VERIFICATION_STATUS；可发布状态必须带 verified_by + verification_note
    （与 app/validation.py 的 NEEDS_VERIFIER 同一套规则，不另立标准）
  - disputed 必须已有 dispute_group，否则交给库的 CHECK 约束直接拒（整批回滚，不留半套数据）
  - 只改 verification_status / verified_by / verification_note / updated_at 四列，
    原文、书名、卷次、年份一个字都不碰——那些要改得走数据包重新导入
  - review_logs 的 reviewer 取 CSV 的 verified_by；该列为空（改回 pending 等场景）时用 --operator
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import fts, schema  # noqa: E402
from app.paths import DB_PATH  # noqa: E402

# 与 app/validation.py 同源：可发布的四种状态必须有人署名与说明
NEEDS_VERIFIER = schema.PUBLISHABLE_STATUS
EDITABLE = ("verification_status", "verified_by", "verification_note", "updated_at")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_csv(path: Path) -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return [], [f"文件编码不是 UTF-8：{path}"]
    reader = csv.DictReader(text.splitlines())
    header = [(name or "").strip() for name in (reader.fieldnames or [])]
    for column in ("evidence_id", "verification_status", "verified_by", "verification_note"):
        if column not in header:
            problems.append(f"表头缺少列 {column}（现有：{header}）")
    if problems:
        return [], problems
    rows = []
    for index, raw in enumerate(reader, start=2):
        if not any((value or "").strip() for value in raw.values()):
            continue
        rows.append({key: (value or "").strip() for key, value in raw.items()})
        rows[-1]["__line"] = index
    return rows, problems


def plan(connection: sqlite3.Connection, rows: list[dict]) -> tuple[list[dict], list[str]]:
    """把每行 CSV 变成一个 UPDATE 计划；任何一行不合规就整批不写。"""
    updates: list[dict] = []
    problems: list[str] = []
    for row in rows:
        line = row["__line"]
        evidence_id = row["evidence_id"]
        status = row["verification_status"]
        reviewer = row["verified_by"]
        note = row["verification_note"]

        if not evidence_id:
            problems.append(f"第 {line} 行：evidence_id 为空")
            continue
        found = connection.execute(
            "SELECT evidence_id, surname_id, verification_status, verified_by, verification_note,"
            " dispute_group, evidence_type FROM evidences WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        if found is None:
            problems.append(f"第 {line} 行：{evidence_id} 不在库里（编号写错了？还是这条尚未导入？）")
            continue
        if status not in schema.VERIFICATION_STATUS:
            problems.append(f"第 {line} 行：状态 {status!r} 不合法，可选 {'、'.join(schema.VERIFICATION_STATUS)}")
            continue
        if status in NEEDS_VERIFIER and not reviewer:
            problems.append(f"第 {line} 行：{status} 是可发布状态，必须有 verified_by（真实成员代号）")
            continue
        if status in NEEDS_VERIFIER and not note:
            problems.append(f"第 {line} 行：{status} 是可发布状态，必须有 verification_note（核对了什么、哪里存疑）")
            continue
        if status == "disputed" and not (found[5] or "").strip():
            problems.append(f"第 {line} 行：{evidence_id} 没有 dispute_group，改成 disputed 会被库约束拒绝")
            continue
        before = {
            "verification_status": found[2],
            "verified_by": found[3],
            "verification_note": found[4],
        }
        after = {
            "verification_status": status,
            "verified_by": reviewer or found[3],
            "verification_note": note or found[4],
        }
        if before == after:
            continue  # 幂等：重复跑同一次核对不产生第二条留痕
        updates.append({"evidence_id": evidence_id, "before": before, "after": after, "row": row})
    return updates, problems


def apply(connection: sqlite3.Connection, updates: list[dict], origin: str, operator: str = "") -> None:
    stamp = now_iso()
    for item in updates:
        row = item["row"]
        note = item["after"]["verification_note"]
        connection.execute(
            "UPDATE evidences SET verification_status = ?, verified_by = ?, verification_note = ?, updated_at = ?"
            " WHERE evidence_id = ?",
            (item["after"]["verification_status"], item["after"]["verified_by"], note, stamp, item["evidence_id"]),
        )
        connection.execute(
            "INSERT INTO review_logs (target_type, target_id, action, reviewer, before_json, after_json,"
            " review_note, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "evidence", item["evidence_id"], f"set_{item['after']['verification_status']}",
                row["verified_by"] or operator, json.dumps(item["before"], ensure_ascii=False),
                json.dumps(item["after"], ensure_ascii=False),
                f"按人工核对结果更新状态（依据文件 {origin}）；改前 {item['before']['verification_status']}"
                f" → 改后 {item['after']['verification_status']}",
                stamp,
            ),
        )


def summarize(connection: sqlite3.Connection, updates: list[dict]) -> None:
    counts: dict[str, int] = {}
    for item in updates:
        key = f"{item['before']['verification_status']} → {item['after']['verification_status']}"
        counts[key] = counts.get(key, 0) + 1
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value} 条")
    print("  库里现在的状态分布：" + "、".join(
        f"{status}={n}"
        for status, n in connection.execute(
            "SELECT verification_status, count(*) FROM evidences GROUP BY 1 ORDER BY 2 DESC"
        )
    ))
    placeholders = ",".join("?" * len(NEEDS_VERIFIER))
    published = connection.execute(
        f"SELECT count(*) FROM evidences WHERE verification_status IN ({placeholders})", NEEDS_VERIFIER
    ).fetchone()[0]
    print(f"  可对外发布（{('、'.join(NEEDS_VERIFIER))}）：{published} 条")


def main() -> int:
    parser = argparse.ArgumentParser(description="按核对结果 CSV 更新证据状态并写 review_logs（默认预演）")
    parser.add_argument("csv_path")
    parser.add_argument("--apply", action="store_true", help="真正写入；缺省只在事务里试改后回滚")
    parser.add_argument("--operator", default="", help="操作人（真实成员代号）；CSV 的 verified_by 为空时用它记 review_logs")
    args = parser.parse_args()

    path = Path(args.csv_path)
    if not path.exists():
        print(f"找不到核对结果文件：{path}", file=sys.stderr)
        return 2
    if not DB_PATH.exists():
        print(f"数据库不存在：{DB_PATH}（先跑 scripts/init_db.py）", file=sys.stderr)
        return 2

    rows, problems = read_csv(path)
    if problems:
        for problem in problems:
            print(f"  [错误] {problem}", file=sys.stderr)
        return 1
    print(f"读入 {path.name}：{len(rows)} 行")

    connection = sqlite3.connect(DB_PATH)
    connection.execute("BEGIN")
    try:
        updates, plan_problems = plan(connection, rows)
        if plan_problems:
            for problem in plan_problems:
                print(f"  [错误] {problem}", file=sys.stderr)
            print("存在不合规行 → 一条也不写（整批回滚）", file=sys.stderr)
            connection.rollback()
            return 1

        print(f"计划更新 {len(updates)} 条（其余行状态本就一致，跳过）")
        if not updates:
            connection.rollback()
            return 0
        apply(connection, updates, origin=path.name, operator=args.operator)
        summarize(connection, updates)
        logs = connection.execute("SELECT count(*) FROM review_logs").fetchone()[0]
        print(f"  review_logs 预演后总条数：{logs}")

        if args.apply:
            connection.commit()
            print(f"已写入 {DB_PATH}，留痕 {len(updates)} 条 review_logs")
            # 必须重建全文索引：app/fts.rebuild 只把可发布状态写进 evidences_fts，
            # 改状态不改原文，不重建就检索不到。rebuild 内部自己 commit，
            # 所以只能在**提交之后**调用；预演分支绝不能碰它，否则会把半截事务写下去。
            indexed = fts.rebuild(connection)
            print(f"  全文索引重建：evidences_fts 内 {indexed} 条可发布证据")
        else:
            connection.rollback()
            print("预演模式：未写库。确认无误后加 --apply")
        return 0
    except sqlite3.Error as exc:
        connection.rollback()
        print(f"  [错误] 写库失败，已整体回滚：{str(exc)[:200]}", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
