"""Alembic 环境（任务 C-01 / C-02）。

连接串来自 app.config（环境变量 / .env），仓库里不存任何连接串。
target_metadata 取 app.db.base 的 Base，并由 import_models() 保证 13 张表全部注册，
否则 autogenerate 会误判“要删表”。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.db.base import Base, import_models  # noqa: E402
from app.db.session import build_engine  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import_models()
target_metadata = Base.metadata


def database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    """离线模式（alembic upgrade --sql）：只生成 SQL，不连库。"""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = build_engine(database_url())
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()