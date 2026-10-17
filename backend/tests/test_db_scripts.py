"""备份/恢复脚本的 CI 安全测试（任务 C-06 的一部分）。

真正需要 PostgreSQL 的部分（pg_dump 产出、空库恢复、重启后数据仍在）只能在服务器上实测，
这里覆盖可以在 CI 离线验证的纯函数：URL 解析、连接参数透传、校验和比对。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import backup_db  # noqa: E402
import restore_db  # noqa: E402


def test_parse_database_url_handles_password_and_params() -> None:
    parsed = backup_db.parse_database_url("postgresql+psycopg://user:p%40ss@db.internal:5433/surname_app?sslmode=require")
    assert parsed["host"] == "db.internal"
    assert parsed["port"] == "5433"
    assert parsed["user"] == "user"
    assert parsed["password"] == "p@ss", "percent-encoded 口令必须解码后交给 PGPASSWORD"
    assert parsed["dbname"] == "surname_app"
    assert parsed["params"] == {"sslmode": "require"}


def test_parse_database_url_defaults() -> None:
    parsed = backup_db.parse_database_url("postgres://u@h")
    assert (parsed["host"], parsed["port"], parsed["dbname"]) == ("h", "5432", "postgres")
    assert parsed["params"] == {}


@pytest.mark.parametrize("url", ["sqlite:///./dev.db", "mysql://u@h/db", "not-a-url"])
def test_parse_database_url_rejects_non_postgresql(url: str) -> None:
    with pytest.raises(SystemExit):
        backup_db.parse_database_url(url)


def test_libpq_env_maps_known_params_and_warns_on_unknown(capsys) -> None:
    env = backup_db.libpq_env({"sslmode": "require", "connect_timeout": "5", "unknown_param": "x"})
    assert env == {"PGSSLMODE": "require", "PGCONNECT_TIMEOUT": "5"}
    assert "unknown_param" in capsys.readouterr().err, "不认识的参数要明确提示，不能静默丢弃"


def test_libpq_env_can_stay_silent() -> None:
    env = backup_db.libpq_env({"nope": "1"}, warn=False)
    assert env == {}


def test_checksum_verification_detects_tampering(tmp_path: Path) -> None:
    dump = tmp_path / "backup.dump"
    dump.write_bytes(b"original-payload")
    digest = backup_db.sha256_of(dump)
    dump.with_suffix(".dump.sha256").write_text(f"{digest}  {dump.name}\n", encoding="utf-8")

    restore_db.verify_checksum(dump)  # 校验和一致：不抛异常

    dump.write_bytes(b"tampered-payload")
    with pytest.raises(SystemExit):
        restore_db.verify_checksum(dump)


def test_checksum_file_missing_is_only_a_notice(tmp_path: Path, capsys) -> None:
    dump = tmp_path / "backup.dump"
    dump.write_bytes(b"payload")
    restore_db.verify_checksum(dump)
    assert "未找到" in capsys.readouterr().out


def test_count_tables_covers_all_business_tables() -> None:
    """恢复后的行数统计必须覆盖数据字典第 2 节的全部业务表。"""
    assert len(restore_db.COUNT_TABLES) == 13
    assert {"evidences", "source_editions", "migration_events", "ingestion_jobs"} <= set(restore_db.COUNT_TABLES)
