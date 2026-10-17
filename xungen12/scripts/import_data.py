#!/usr/bin/env python3
"""数据导入脚本（任务 C-09）：把通过校验的数据包写进 data/xungen.db。

用法（在项目目录下）：
    python3 scripts/import_data.py data/verified --operator B --dry-run   # 只校验不写库（默认就是 dry-run）
    python3 scripts/import_data.py data/verified --operator B --apply     # 真正写入
    python3 scripts/import_data.py data/verified/evidences.csv --operator B --apply --stats-out docs/db-stats-20261017.json

行为约定（执行清单 §一.5、§1.3、§1.5、十一 停线规则）：
  - 先跑 validate_package（同一套规则），有错就**整体不写入**；
  - 写入在一个事务里完成，任何一步失败全部回滚，并把本次导入统计与错误写进 ingestion_jobs；
  - 错误信息给「文件 + 行号 + 字段 + 原因 + 修复建议」；
  - 不用 sudo、不装第三方包、不改动别的目录。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, fts, schema, validation  # noqa: E402
from app.paths import DB_PATH, ensure_dirs  # noqa: E402

PACKAGE_ORDER = ("source_register.csv", "evidences.csv", "places.csv", "migrations.csv", "corpus_searches.csv")
JOB_ATTEMPTS = 5


@dataclass
class Outcome:
    job_id: str
    operator: str
    dry_run: bool
    files: list[str] = field(default_factory=list)
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    rolled_back: bool = False
    indexed: int = 0
    errors: list[dict] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id, "operator": self.operator, "dry_run": self.dry_run, "files": self.files,
            "total": self.total, "accepted": self.accepted, "rejected": self.rejected,
            "rolled_back": self.rolled_back, "indexed": self.indexed, "errors": self.errors,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_files(target: Path) -> list[Path]:
    """单个文件直接用；目录模式收固定的 CSV 名 + 所有 *.json（JSON 里用 kind 或文件名区分种类）。"""
    if target.is_file():
        return [target]
    if target.is_dir():
        csvs = [target / name for name in PACKAGE_ORDER if (target / name).exists()]
        jsons = sorted(path for path in target.glob("*.json") if path.name != "schema_version.json")
        return csvs + jsons
    return []


def next_job_id(connection: sqlite3.Connection) -> str:
    prefix = f"JOB-{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
    last = db.scalar(connection, "SELECT job_id FROM ingestion_jobs WHERE job_id LIKE ? ORDER BY job_id DESC LIMIT 1",
                     (f"{prefix}%",))
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:03d}"


def reserve_job(connection: sqlite3.Connection, *, input_ref: str, operator: str, started_at: str) -> str:
    """先占住 job_id 再写数据：并发导入撞号时换下一个号，不让整次导入失败。"""
    for _ in range(JOB_ATTEMPTS):
        job_id = next_job_id(connection)
        try:
            connection.execute(
                "INSERT INTO ingestion_jobs (job_id, source, input_ref, operator, total, accepted, rejected, "
                "rolled_back, error_json, started_at, finished_at) VALUES (?,?,?,?,0,0,0,0,NULL,?,NULL)",
                (job_id, Path(input_ref).name, input_ref, operator, started_at),
            )
            connection.commit()
            return job_id
        except sqlite3.IntegrityError:
            connection.rollback()
    raise SystemExit(f"并发导入冲突：job_id 连续 {JOB_ATTEMPTS} 次撞号，请稍后重试")


def finish_job(connection: sqlite3.Connection, job_id: str, outcome: Outcome) -> None:
    connection.execute(
        "UPDATE ingestion_jobs SET total=?, accepted=?, rejected=?, rolled_back=?, error_json=?, finished_at=? "
        "WHERE job_id=?",
        (
            outcome.total, outcome.accepted, outcome.rejected, int(outcome.rolled_back),
            json.dumps(outcome.errors, ensure_ascii=False) if outcome.errors else None,
            outcome.finished_at, job_id,
        ),
    )
    connection.commit()


def _issue(row: int, field_name: str | None, reason: str, fix: str = "") -> dict:
    return {"row": row, "field": field_name, "reason": reason, "fix": fix}


def validate_inputs(files: list[Path], connection: sqlite3.Connection) -> tuple[list[dict], dict[str, list], int]:
    """校验全部文件，并检查与库里已有数据是否冲突。返回 (错误列表, 按种类的行, 总记录数)。"""
    known_evidence = set()
    for path in files:
        if validation.FILENAME_KIND.get(path.name.lower()) == "evidences":
            known_evidence |= validation.collect_evidence_ids(path)

    rows_by_kind: dict[str, list] = {}
    errors: list[dict] = []
    total = 0
    for path in files:
        report = validation.validate_package(path, known_evidence=known_evidence)
        total += report.rows
        for issue in report.errors:
            errors.append(_issue(issue.row, issue.field, f"{path.name}：{issue.reason}", issue.fix))
        kind, raw_rows, _ = validation.read_package(path)
        normalized = []
        for raw in raw_rows:
            row = validation.normalize_row(raw)
            row["__line"] = raw["__line"]
            normalized.append(row)
        rows_by_kind[kind] = normalized

    # 与库里已有数据冲突（编号唯一）：提前报错，避免写库时炸在事务里
    checks = (
        ("evidences", "evidence_id", "SELECT evidence_id FROM evidences", "证据编号已入库"),
        ("source_register", "source_code", "SELECT source_code FROM source_works", "来源编号已入库"),
        ("migrations", "migration_code", "SELECT migration_code FROM migration_events", "迁徙编号已入库"),
        ("corpus_searches", "search_code", "SELECT search_code FROM corpus_searches", "语料审计编号已入库"),
    )
    for kind, field_name, sql, label in checks:
        existing = {row[0] for row in db.query_all(connection, sql)}
        for row in rows_by_kind.get(kind, []):
            value = row.get(field_name)
            if value and value in existing:
                errors.append(_issue(int(row["__line"]), field_name, f"{label}：{value}（重复导入）",
                                     "编号不得复用；如确需更新记录，请先人工核验后走 review_logs 流程"))
    return errors, rows_by_kind, total


def import_rows(connection: sqlite3.Connection, rows_by_kind: dict[str, list]) -> int:
    """在**一个事务**里写入全部记录，返回写入条数；异常由调用方回滚。"""
    written = 0
    surnames: dict[str, int] = {}

    def surname_id(name: str) -> int:
        if name in surnames:
            return surnames[name]
        row = db.query_one(connection, "SELECT id FROM surnames WHERE name = ?", (name,))
        if row:
            surnames[name] = row["id"]
            return row["id"]
        cursor = connection.execute(
            "INSERT INTO surnames (name, category, status) VALUES (?,?, 'published')",
            (name, "single" if len(name) == 1 else "compound"),
        )
        surnames[name] = cursor.lastrowid
        return surnames[name]

    for row in rows_by_kind.get("source_register", []):
        connection.execute(
            "INSERT INTO source_works (source_code, title, author, dynasty, work_type, edition, source_provider,"
            " source_url, license_status, accessed_at, content_hash, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["source_code"], row["source_title"], row["source_author"], row.get("dynasty") or None,
                row["work_type"], row.get("edition") or None, row.get("source_provider") or None,
                row.get("source_url") or None, row["license_status"], row.get("accessed_at") or None,
                row.get("content_hash") or None, row.get("notes") or None,
            ),
        )
        written += 1

    for row in rows_by_kind.get("evidences", []):
        connection.execute(
            "INSERT INTO evidences (evidence_id, surname_id, evidence_type, claim_text, original_excerpt,"
            " volume_or_section, page_or_location, source_code, source_title, source_url, year_start, year_end,"
            " time_label, verification_status, confidence, verified_by, verification_note, dispute_group)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["evidence_id"], surname_id(row["surname"]), row["evidence_type"], row["claim_text"],
                row["original_excerpt"], row["volume_or_section"], row.get("page_or_location") or None,
                row.get("source_code") or None, row["source_title"], row["source_url"],
                int(row["year_start"]) if row.get("year_start") else None,
                int(row["year_end"]) if row.get("year_end") else None,
                row.get("time_label") or None, row["verification_status"], row["confidence"],
                row.get("verified_by") or None, row.get("verification_note") or None,
                row.get("dispute_group") or None,
            ),
        )
        written += 1

    places: dict[tuple[str, str], int] = {}

    def place_id(row: dict, side: str) -> int | None:
        name = row.get(f"{side}_historical_name")
        if not name:
            return None
        status = row.get(f"{side}_location_status") or "approximate"
        key = (name, status)
        if key in places:
            return places[key]
        found = db.query_one(connection, "SELECT id FROM places WHERE historical_name = ? AND location_status = ?",
                             (name, status))
        if found:
            places[key] = found["id"]
            return found["id"]
        cursor = connection.execute(
            "INSERT INTO places (historical_name, modern_name, period, location_status, coordinates, location_note)"
            " VALUES (?,?,?,?,?,?)",
            (name, row.get(f"{side}_modern_name") or None, None, status,
             row.get(f"{side}_coordinates") or None, row.get(f"{side}_location_note") or None),
        )
        places[key] = cursor.lastrowid
        return places[key]

    for row in rows_by_kind.get("places", []):
        connection.execute(
            "INSERT INTO places (historical_name, modern_name, period, location_status, coordinates, location_note)"
            " VALUES (?,?,?,?,?,?)",
            (row["historical_name"], row.get("modern_name") or None, row.get("period") or None,
             row["location_status"], row.get("coordinates") or None, row.get("location_note") or None),
        )
        written += 1

    for row in rows_by_kind.get("migrations", []):
        cursor = connection.execute(
            "INSERT INTO migration_events (migration_code, surname_id, from_place_id, to_place_id, time_label,"
            " year_start, year_end, event_summary, relation_status, confidence, verified_by, verification_note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["migration_code"], surname_id(row["surname"]), place_id(row, "from"), place_id(row, "to"),
                row["time_label"],
                int(row["year_start"]) if row.get("year_start") else None,
                int(row["year_end"]) if row.get("year_end") else None,
                row["event_summary"], row["relation_status"], row["confidence"],
                row.get("verified_by") or None, row.get("verification_note") or None,
            ),
        )
        event_id = cursor.lastrowid
        ids = [item.strip() for item in re.split(r"[;；,，]", row.get("evidence_ids", "")) if item.strip()]
        for evidence_id in ids:
            connection.execute(
                "INSERT INTO migration_event_evidences (migration_event_id, evidence_id, relation_type) VALUES (?,?,?)",
                (event_id, evidence_id, row.get("relation_type") or None),
            )
        written += 1

    for row in rows_by_kind.get("corpus_searches", []):
        connection.execute(
            "INSERT INTO corpus_searches (search_code, surname_id, corpus_name, query_text, checked_at,"
            " result_count, no_result_reason, operator, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                row["search_code"], surname_id(row["surname"]), row["corpus_name"], row["query_text"],
                row["checked_at"], int(row["result_count"]), row.get("no_result_reason") or None,
                row["operator"], row.get("note") or None,
            ),
        )
        written += 1

    return written


def write_stats(connection: sqlite3.Connection, out_path: Path) -> dict:
    """导入后统计（执行清单 §1.5）：行数 + 按姓氏/类型的分布。"""
    stats = {
        "generated_at": now_iso(),
        "db": str(DB_PATH),
        "tables": {name: db.scalar(connection, f"SELECT count(*) FROM {name}") for name in schema.TABLES},
        "evidences_by_status": {
            row["verification_status"]: row["n"]
            for row in db.query_all(connection, "SELECT verification_status, count(*) AS n FROM evidences GROUP BY 1")
        },
        "evidences_by_type": {
            row["evidence_type"]: row["n"]
            for row in db.query_all(connection, "SELECT evidence_type, count(*) AS n FROM evidences GROUP BY 1")
        },
        "audit_by_surname": [
            {"surname": row["name"], "queries": row["q"], "hits": row["hits"]}
            for row in db.query_all(
                connection,
                "SELECT s.name, count(c.id) AS q, COALESCE(sum(c.result_count), 0) AS hits"
                "  FROM surnames s JOIN corpus_searches c ON c.surname_id = s.id"
                " GROUP BY s.name ORDER BY hits DESC, q DESC, s.name LIMIT 20",
            )
        ],
        "evidences_by_surname": [
            {"surname": row["name"], "n": row["n"]}
            for row in db.query_all(
                connection,
                "SELECT s.name, count(e.id) AS n FROM surnames s JOIN evidences e ON e.surname_id = s.id "
                "GROUP BY s.name ORDER BY n DESC, s.name LIMIT 50",
            )
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",  # 显式 LF：Windows 上避免写成 CRLF 而让 git 认为文件被改过
    )
    return stats


def run(target: Path, operator: str, *, apply: bool, stats_out: Path | None = None) -> Outcome:
    started = now_iso()
    files = collect_files(target)
    outcome = Outcome(job_id="", operator=operator, dry_run=not apply, files=[str(path) for path in files],
                      started_at=started)
    if not files:
        outcome.errors.append(_issue(0, None, f"没有可导入的数据文件：{target}",
                                     "传入 data/ 下的数据包目录或单个 CSV/JSON 文件"))
        outcome.finished_at = now_iso()
        return outcome

    ensure_dirs()
    connection = db.connect()
    try:
        outcome.job_id = reserve_job(connection, input_ref=str(target), operator=operator, started_at=started)
        errors, rows_by_kind, total = validate_inputs(files, connection)
        outcome.total = total
        outcome.errors = errors

        if errors:
            outcome.rejected = len({item["row"] for item in errors if item["row"]}) or 1
            outcome.rolled_back = apply
            outcome.finished_at = now_iso()
            finish_job(connection, outcome.job_id, outcome)
            return outcome

        if apply:
            try:
                outcome.accepted = import_rows(connection, rows_by_kind)
                # 导入后必须重建全文索引，否则新数据检索不到（FTS5 不可用时返回 0，检索走 LIKE）
                indexed = fts.rebuild(connection)
                connection.commit()
                outcome.indexed = indexed
            except sqlite3.Error as exc:
                connection.rollback()
                outcome.errors.append(_issue(0, None, f"写库失败，已整体回滚：{str(exc)[:160]}",
                                             "先跑 validate_package.py 定位问题行，再重新导入"))
                outcome.accepted = 0
                outcome.rejected = total
                outcome.rolled_back = True
                outcome.finished_at = now_iso()
                finish_job(connection, outcome.job_id, outcome)
                return outcome
        else:
            outcome.accepted = sum(len(rows) for rows in rows_by_kind.values())

        if stats_out is not None and apply:
            write_stats(connection, stats_out)
        outcome.finished_at = now_iso()
        finish_job(connection, outcome.job_id, outcome)
        return outcome
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="导入数据包到 data/xungen.db（默认 dry-run）")
    parser.add_argument("target", nargs="?", default="", help="数据包目录或单个 CSV/JSON 文件（--stats-only 时可省略）")
    parser.add_argument("--operator", default="", help="操作人（真实成员代号，如 B）；--stats-only 时不需要")
    parser.add_argument("--apply", action="store_true", help="真正写入；缺省只校验")
    parser.add_argument("--stats-out", default="", help="导入后统计写到哪个文件（如 docs/db-stats-20261017.json）")
    parser.add_argument("--stats-only", action="store_true",
                        help="不导入，只从现行库重算统计并写到 --stats-out（部署后重新生成统计、不重复导入时用）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果（便于脚本消费）")
    args = parser.parse_args()

    stats_path = Path(args.stats_out) if args.stats_out else None
    if not args.stats_only and not args.operator:
        print("--operator 是必填（--stats-only 模式除外）", file=sys.stderr)
        return 2
    if args.stats_only:
        if stats_path is None:
            print("--stats-only 需要同时给 --stats-out", file=sys.stderr)
            return 2
        from app.paths import DB_PATH as db_file

        if not db_file.exists():
            print(f"数据库不存在：{db_file}（先跑 scripts/init_db.py）", file=sys.stderr)
            return 2
        connection = db.connect()
        try:
            stats = write_stats(connection, stats_path)
        finally:
            connection.close()
        print(f"已重算统计 → {stats_path}")
        print("  " + "、".join(f"{k}={v}" for k, v in stats["tables"].items() if v))
        print(f"  生成时间 {stats['generated_at']}（数据来自 {stats['db']}）")
        return 0

    outcome = run(Path(args.target), args.operator, apply=args.apply, stats_out=stats_path)

    if args.json:
        print(json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"任务号 {outcome.job_id}｜操作人 {outcome.operator}｜{'已写入' if args.apply else 'dry-run（未写库）'}")
        print(f"文件 {len(outcome.files)} 个｜记录 {outcome.total} 条｜通过 {outcome.accepted}｜拒绝 {outcome.rejected}"
              + ("｜已整体回滚" if outcome.rolled_back else ""))
        for item in outcome.errors[:20]:
            where = f"第 {item['row']} 行" if item["row"] else "整份文件"
            print(f"  [错误] {where} {item['field'] or '文件'}：{item['reason']}"
                  + (f"（修复：{item['fix']}）" if item["fix"] else ""))
        if len(outcome.errors) > 20:
            print(f"  ……还有 {len(outcome.errors) - 20} 条错误，见 ingestion_jobs.error_json")
        if not args.apply and not outcome.errors:
            print("校验通过。确认无误后加 --apply 写入；建议随后跑 python3 scripts/contract_tests.py")
    return 1 if outcome.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
