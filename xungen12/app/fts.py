"""全文索引维护（FTS5 可用时用索引，不可用时静止退化）。

为什么单独一个模块：init_db 建完表要建索引、导入后要重建索引、检索时要查索引，
三处必须用同一套 DDL 与同一份可见性规则（pending 不进索引）。
"""

from __future__ import annotations

import sqlite3

from . import db, schema


def available(connection: sqlite3.Connection) -> bool:
    """库里是否已有可用的 FTS5 索引（没有就回落 LIKE）。"""
    if not db.has_fts5(connection):
        return False
    row = db.query_one(connection, "SELECT name FROM sqlite_master WHERE type='table' AND name='evidences_fts'")
    return row is not None


def ensure_index(connection: sqlite3.Connection) -> str:
    """建索引（幂等）。返回 ready / unavailable。"""
    if not db.has_fts5(connection):
        return "unavailable"
    try:
        for statement in schema.FTS_STATEMENTS:
            connection.execute(statement)
        connection.commit()
    except sqlite3.OperationalError:
        # 例如旧版 SQLite 不支持 trigram 分词器：不建索引，检索走 LIKE
        connection.rollback()
        return "unavailable"
    return "ready"


def rebuild(connection: sqlite3.Connection) -> int:
    """按当前证据表重建索引；返回索引条数。数据导入后必须调用一次。"""
    if not available(connection):
        return 0
    connection.execute("DELETE FROM evidences_fts")
    cursor = connection.execute(
        "INSERT INTO evidences_fts (evidence_id, claim_text, original_excerpt, volume_or_section) "
        "SELECT evidence_id, claim_text, original_excerpt, volume_or_section FROM evidences "
        "WHERE verification_status IN ('verified', 'disputed', 'link_stale', 'retracted')"
    )
    connection.commit()
    return cursor.rowcount
