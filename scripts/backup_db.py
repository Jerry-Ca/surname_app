#!/usr/bin/env python3
"""数据库备份（任务 C-06）：产出带时间戳的 dump 与校验和。

用法：
    python scripts/backup_db.py --out /srv/backups
    python scripts/backup_db.py --out ./backups --label day3-before-demo

只在 PostgreSQL 上工作；SQLite 是本地调试用的临时库，不作为需要备份的对象。
连接信息从 DATABASE_URL 读取（格式：postgresql+psycopg://user:pass@host:port/dbname）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse


def parse_database_url(url: str) -> dict:
    """把 DATABASE_URL 拆成 pg_dump/pg_restore 需要的连接参数。

    支持 postgresql+psycopg:// 与 postgresql:// 两种写法；SQLite 直接拒绝。
    """
    scheme = url.split("://", 1)[0] if "://" in url else url
    if scheme.split("+", 1)[0] not in {"postgresql", "postgres"}:
        raise SystemExit(
            f"备份只支持 PostgreSQL，当前 DATABASE_URL 是 {scheme}。\n"
            "正式环境必须使用 PostgreSQL（见 docs/architecture.md 第 2 节）。"
        )
    parsed = urlparse("//" + url.split("://", 1)[1])
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "dbname": (parsed.path or "/postgres").lstrip("/"),
    }


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL 备份")
    parser.add_argument("--out", default="backups", help="备份目录，默认 backups/")
    parser.add_argument("--label", default="", help="附加标签，例如 day3-before-demo")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""), help="默认读取环境变量 DATABASE_URL")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("缺少 DATABASE_URL（本机可在仓库根目录 .env 中配置，服务器上用 /etc/surname_app.env）")
    conn = parse_database_url(args.database_url)

    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise SystemExit("未找到 pg_dump，请先安装 postgresql-client")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{args.label}" if args.label else ""
    target = out_dir / f"surname_app-{stamp}{suffix}.dump"

    env = dict(os.environ, PGPASSWORD=conn["password"])
    command = [
        pg_dump,
        "-h", conn["host"],
        "-p", conn["port"],
        "-U", conn["user"],
        "-d", conn["dbname"],
        "-Fc",               # 自定义格式：可用 pg_restore 选择性恢复
        "--no-owner",
        "-f", str(target),
    ]
    print("执行：", " ".join(command[:8]), "...")
    completed = subprocess.run(command, env=env, capture_output=True, text=True)
    if completed.returncode != 0:
        print(completed.stderr.strip()[:800], file=sys.stderr)
        return completed.returncode

    digest = sha256_of(target)
    checksum_file = target.with_suffix(target.suffix + ".sha256")
    checksum_file.write_text(f"{digest}  {target.name}\n", encoding="utf-8")

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"备份完成：{target}（{size_mb:.2f} MB）")
    print(f"校验和：{digest}")
    print(f"校验文件：{checksum_file}")
    print("恢复方式：python scripts/restore_db.py --file " + str(target) + " --yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())