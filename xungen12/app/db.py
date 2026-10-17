"""SQLite 连接与只读查询助手（只用标准库 sqlite3）。

约定：
  - 每次连接都打开外键约束（SQLite 默认关闭，不开等于没有外键）；
  - 查询走只读连接（mode=ro），写库只在导入脚本里发生，避免服务把库改坏；
  - 设 busy_timeout，避免与备份/导入并发时立刻报 database is locked。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .paths import DB_PATH

BUSY_TIMEOUT_MS = 5000


def connect(path: Path | str = DB_PATH, *, readonly: bool = False) -> sqlite3.Connection:
    """打开数据库连接；readonly=True 时用 URI 只读模式。"""
    target = Path(path)
    if readonly:
        connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
    else:
        connection = sqlite3.connect(str(target), timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return connection


def query_all(connection: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
    return list(connection.execute(sql, tuple(params)))


def query_one(connection: sqlite3.Connection, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
    return connection.execute(sql, tuple(params)).fetchone()


def table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")
    return [row[0] for row in rows]


def has_fts5(connection: sqlite3.Connection) -> bool:
    """检测 FTS5 是否可用（共享服务器上的 Python 可能没带 FTS5，必须能降级）。"""
    try:
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.fts_probe USING fts5(x)")
        connection.execute("DROP TABLE IF EXISTS temp.fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def scalar(connection: sqlite3.Connection, sql: str, params: Iterable = ()):
    row = connection.execute(sql, tuple(params)).fetchone()
    return row[0] if row else None
