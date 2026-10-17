#!/usr/bin/env python3
"""建库脚本（任务 C-08）：创建 data/xungen.db、全部表与约束，并写 schema 版本。

用法（在项目目录下）：
    python3 scripts/init_db.py            # 建库（幂等）
    python3 scripts/init_db.py --check    # 只检查现有库的结构与版本，不修改
    python3 scripts/init_db.py --rebuild-fts   # 重建全文索引（FTS5 可用时）

约定（执行清单 §1.1 / §1.2 / §1.4）：
  - 数据库只能是 data/xungen.db，临时库放 data/tmp/；
  - schema 版本写在 data/schema_version.txt，当前为 1；版本不一致时**拒绝**改动，先人工确认；
  - 所有约束写在 SQLite 的 CHECK/NOT NULL/UNIQUE 里，不靠应用层自觉。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, schema  # noqa: E402
from app.paths import DB_PATH, SCHEMA_VERSION, SCHEMA_VERSION_FILE, TMP_DIR, ensure_dirs  # noqa: E402


def read_version() -> str | None:
    if SCHEMA_VERSION_FILE.exists():
        return SCHEMA_VERSION_FILE.read_text(encoding="utf-8").strip()
    return None


def write_version(version: str = SCHEMA_VERSION) -> None:
    SCHEMA_VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")


def create_schema(connection: sqlite3.Connection) -> None:
    for statement in schema.SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.commit()


def create_fts(connection: sqlite3.Connection) -> str:
    """FTS5 可用则建全文索引；不可用返回原因，服务端会自动回落 LIKE。"""
    if not db.has_fts5(connection):
        return "unavailable"
    for statement in schema.FTS_STATEMENTS:
        connection.execute(statement)
    connection.commit()
    rebuild_fts(connection)
    return "ready"


def rebuild_fts(connection: sqlite3.Connection) -> int:
    if not db.has_fts5(connection):
        return 0
    connection.execute("DELETE FROM evidences_fts")
    cursor = connection.execute(
        "INSERT INTO evidences_fts (evidence_id, claim_text, original_excerpt, volume_or_section) "
        "SELECT evidence_id, claim_text, original_excerpt, volume_or_section FROM evidences "
        "WHERE verification_status IN ('verified', 'disputed', 'link_stale', 'retracted')"
    )
    connection.commit()
    return cursor.rowcount


def check(connection: sqlite3.Connection) -> list[str]:
    """检查表是否齐、版本是否一致；返回问题列表（空表示通过）。"""
    problems: list[str] = []
    existing = set(db.table_names(connection))
    missing = [name for name in schema.TABLES if name not in existing]
    if missing:
        problems.append(f"缺少表：{'、'.join(missing)}")
    version = read_version()
    if version is None:
        problems.append(f"缺少 {SCHEMA_VERSION_FILE.name}（应为 {SCHEMA_VERSION}）")
    elif version != SCHEMA_VERSION:
        problems.append(f"schema 版本是 {version}，脚本期望 {SCHEMA_VERSION}：结构变更需先备份并更新说明")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="建 SQLite 库与约束（任务 C-08）")
    parser.add_argument("--db", default=str(DB_PATH), help="数据库路径，默认 data/xungen.db（不要改）")
    parser.add_argument("--check", action="store_true", help="只检查，不修改")
    parser.add_argument("--rebuild-fts", action="store_true", help="重建全文索引后退出")
    args = parser.parse_args()

    ensure_dirs()
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db)
    if db_path.name != "xungen.db":
        print(f"拒绝：数据库只能是 data/xungen.db（收到 {db_path.name}）", file=sys.stderr)
        return 2

    if args.check:
        if not db_path.exists():
            print(f"数据库不存在：{db_path}")
            return 1
        with db.connect(db_path, readonly=True) as connection:
            problems = check(connection)
        print("检查通过：表齐全，schema 版本一致" if not problems else "检查未通过：" + "；".join(problems))
        return 0 if not problems else 1

    existed = db_path.exists()
    version_before = read_version()
    if existed and version_before and version_before != SCHEMA_VERSION:
        print(
            f"拒绝改动：现有库 schema 版本 {version_before}，脚本版本 {SCHEMA_VERSION}。\n"
            "结构变更的正确顺序：先备份（scripts/backup.sh）→ 更新迁移说明与 api-contract → 再改结构。",
            file=sys.stderr,
        )
        return 2

    with db.connect(db_path) as connection:
        create_schema(connection)
        fts_state = create_fts(connection)
        existing = set(db.table_names(connection))
        missing = [name for name in schema.TABLES if name not in existing]
        if missing:  # 建表语句出错时必须马上停下，不能让服务带着残缺的表结构启动
            print(f"建库失败：缺少表 {'、'.join(missing)}", file=sys.stderr)
            return 3
        counts = {name: db.scalar(connection, f"SELECT count(*) FROM {name}") for name in schema.TABLES}
    write_version()

    print(f"{'已存在的库，结构补全' if existed else '已新建数据库'}：{db_path}")
    print(f"表（{len(schema.TABLES)} 张）：{'、'.join(schema.TABLES)}")
    print(f"全文索引：FTS5 {fts_state}" + ("（服务端自动回落 LIKE 检索）" if fts_state == "unavailable" else ""))
    print(f"schema 版本：{SCHEMA_VERSION} → {SCHEMA_VERSION_FILE}")
    print("行数：" + "、".join(f"{name}={counts[name]}" for name in schema.TABLES))
    print("\n下一步：python3 scripts/import_data.py --input <数据包> --operator <成员> 导入数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
