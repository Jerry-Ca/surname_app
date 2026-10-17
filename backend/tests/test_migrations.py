"""迁移可用性（任务 C-02 验收项）。

验收要求：在空库上 `alembic upgrade head` 一次建齐全部表、外键、状态字段与索引；
`downgrade base` 能干净回滚；重复 `upgrade head` 不报错。

这里在测试库上真实跑一遍（不是看文件），因为迁移写错时最需要被拦住的是人，不是代码。
"""

from __future__ import annotations

from alembic import command
from conftest import alembic_config
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings

# data-dictionary.md 第 2 节列出的全部表（正文写“12 张表”，实际列出 13 张，
# 差异已在 PR 中提请 A 修正文档措辞）
EXPECTED_TABLES = {
    "surnames",
    "surname_aliases",
    "source_works",
    "source_editions",
    "evidences",
    "evidence_sources",
    "places",
    "migration_events",
    "migration_event_evidences",
    "corpus_searches",
    "review_logs",
    "embedding_chunks",
    "ingestion_jobs",
}


def _table_names() -> set[str]:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        names = set(inspect(connection).get_table_names())
    engine.dispose()
    return names


def _columns(table: str) -> set[str]:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns(table)}
    engine.dispose()
    return columns


def test_upgrade_head_creates_all_tables_on_empty_database() -> None:
    command.downgrade(alembic_config(), "base")
    try:
        # alembic_version 是 Alembic 自己的版本表，不属于业务表
        assert _table_names() - {"alembic_version"} == set(), "downgrade base 之后不应残留业务表"
    finally:
        # 无论断言是否通过，都把测试库恢复到 head，避免影响其余用例
        command.upgrade(alembic_config(), "head")
    assert _table_names() >= EXPECTED_TABLES


def test_revision_recorded_for_health_endpoint() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    # /api/health 的 database.migration_revision 读的就是这个值（契约第 3 节）
    assert revision == "0001_initial"


def test_upgrade_head_is_idempotent() -> None:
    command.upgrade(alembic_config(), "head")
    command.upgrade(alembic_config(), "head")  # 再来一次不允许报错
    assert _table_names() >= EXPECTED_TABLES


def test_status_and_foreign_key_columns_exist() -> None:
    # 状态字段是“不删除数据”原则的载体，缺一个就无法表达撤回/争议/链接待复查
    assert {"verification_status", "dispute_group", "evidence_type"} <= _columns("evidences")
    assert {"license_status", "link_status", "source_code"} <= _columns("source_editions")
    assert {"location_status", "coordinates"} <= _columns("places")
    assert {"relation_status", "confidence"} <= _columns("migration_events")
    assert {"no_result_reason", "result_count"} <= _columns("corpus_searches")
    assert {"error_log", "rejected", "rolled_back"} <= _columns("ingestion_jobs")

    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        evidence_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("evidences")}
        source_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("evidence_sources")}
    engine.dispose()
    assert evidence_fks == {"surnames"}
    assert source_fks == {"evidences", "source_editions"}
