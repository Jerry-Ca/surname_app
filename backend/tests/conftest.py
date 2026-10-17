"""测试公共配置。

必须在导入 app 之前设置环境变量：Settings 是 lru_cache 的，导入后不可改。
数据库用临时 SQLite 文件，并且**真正跑一遍 Alembic 迁移**建表——
测试库也不允许 create_all（AGENTS.md 铁律 5），否则迁移坏了测试却是绿的。
CI 不调用任何外部服务，因此这里显式清空模型与向量配置（验证降级路径）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TMP_DIR = Path(tempfile.mkdtemp(prefix="surname_app_tests_"))

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["EMBEDDING_API_KEY"] = ""
os.environ["EMBEDDING_MODEL"] = ""
os.environ["ADMIN_TOKEN"] = "test-admin-token"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def alembic_config():
    """指向仓库 migrations/ 的 Alembic 配置，供测试与迁移测试共用。"""
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def run_migrations(revision: str = "head") -> None:
    from alembic import command

    command.upgrade(alembic_config(), revision)


run_migrations()


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def db_session():
    """直连测试库的会话；由用例自己决定何时 commit。"""
    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_tables():
    """每个用例开始前清空业务表，保证用例之间互不影响。

    只删 Base.metadata 里的业务表；alembic_version 保留，否则每个用例都要重跑迁移。
    """
    from sqlalchemy import inspect

    from app.db.base import Base, import_models
    from app.db.session import get_engine

    import_models()
    engine = get_engine()
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in existing:
                connection.execute(table.delete())
    yield
