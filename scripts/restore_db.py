#!/usr/bin/env python3
"""数据库恢复（任务 C-06）：在空库上完成初始化 + 恢复，并输出恢复后的行数统计。

用法：
    python scripts/restore_db.py --file /srv/backups/surname_app-20261019-030000.dump --yes

会先校验 dump 的 sha256（存在 .sha256 文件时），再执行 pg_restore --clean --if-exists。
--clean 会覆盖现有对象，因此必须显式加 --yes。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_db import parse_database_url  # noqa: E402

COUNT_TABLES = [
    "surnames", "surname_aliases", "source_works", "source_editions",
    "evidences", "evidence_sources", "places", "migration_events",
    "migration_event_evidences", "corpus_searches", "review_logs", "ingestion_jobs",
]


def verify_checksum(dump: Path) -> None:
    checksum_file = dump.with_suffix(dump.suffix + ".sha256")
    if not checksum_file.exists():
        print("提示：未找到 .sha256 校验文件，跳过校验和比对。")
        return
    expected = checksum_file.read_text(encoding="utf-8").split()[0].strip()
    digest = hashlib.sha256()
    with dump.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        raise SystemExit(f"校验和不匹配，dump 可能损坏：期望 {expected[:16]}…，实际 {actual[:16]}…")
    print(f"校验和通过：{actual[:16]}…")


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL 恢复")
    parser.add_argument("--file", required=True, help="pg_dump 产出的 .dump 文件")
    parser.add_argument("--yes", action="store_true", help="确认覆盖现有数据库")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""), help="默认读取环境变量 DATABASE_URL")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("恢复会覆盖现有对象，请确认后加 --yes 执行。")
    if not args.database_url:
        raise SystemExit("缺少 DATABASE_URL")

    dump = Path(args.file)
    if not dump.exists():
        raise SystemExit(f"文件不存在：{dump}")

    verify_checksum(dump)
    conn = parse_database_url(args.database_url)

    pg_restore = shutil.which("pg_restore")
    if not pg_restore:
        raise SystemExit("未找到 pg_restore，请先安装 postgresql-client")

    env = dict(os.environ, PGPASSWORD=conn["password"])
    command = [
        pg_restore,
        "-h", conn["host"],
        "-p", conn["port"],
        "-U", conn["user"],
        "-d", conn["dbname"],
        "--clean", "--if-exists", "--no-owner",
        str(dump),
    ]
    print(f"正在恢复 {dump.name} → {conn['dbname']}@{conn['host']}")
    completed = subprocess.run(command, env=env, capture_output=True, text=True)
    # pg_restore 在没有严重错误时返回 0；-c 清理不存在的对象会产生 warning 级输出
    if completed.returncode != 0:
        print(completed.stderr.strip()[:1200], file=sys.stderr)
        return completed.returncode

    print("恢复完成，行数统计：")
    psql = shutil.which("psql")
    if not psql:
        print("（未找到 psql，跳过行数统计）")
        return 0
    for table in COUNT_TABLES:
        query = f"SELECT count(*) FROM {table};"
        result = subprocess.run(
            [psql, "-h", conn["host"], "-p", conn["port"], "-U", conn["user"], "-d", conn["dbname"], "-tAc", query],
            env=env, capture_output=True, text=True,
        )
        value = result.stdout.strip() if result.returncode == 0 else "表不存在或未迁移"
        print(f"  {table:<22} {value}")
    print()
    print("恢复后请立即验证：curl -s http://127.0.0.1:8000/api/health")
    return 0


if __name__ == "__main__":
    sys.exit(main())