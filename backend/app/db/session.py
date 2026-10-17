"""数据库连接与会话（C 主责）。

设计原则：任何数据库问题都不允许让应用启动失败。
连接不通时 /api/health 报 database_unavailable，其余接口按契约返回空结果或 503。

SQLite 只用于本地与测试：内存库必须用 StaticPool，否则每个连接各拿到一个空库。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..config import get_settings

_ENGINE: Any = None
_SESSION_FACTORY: Any = None


def engine_kwargs(url: str) -> dict:
    """SQLite 与 PostgreSQL 共用的引擎参数（Alembic 也用这一份，避免两套连接逻辑）。"""
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url.endswith("sqlite://"):
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    return kwargs


def build_engine(url: str) -> Any:
    """创建引擎；SQLite 上打开外键约束，让测试与本地调试也能发现外键错误。"""
    from sqlalchemy import create_engine, event

    engine = create_engine(url, **engine_kwargs(url))
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:  # pragma: no cover - 连接钩子
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        settings = get_settings()
        _ENGINE = build_engine(settings.database_url)
    return _ENGINE


def get_session_factory() -> Any:
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        from sqlalchemy.orm import sessionmaker

        _SESSION_FACTORY = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SESSION_FACTORY


def reset_engine() -> None:
    """测试用：强制下次调用重新建引擎与会话工厂。"""
    global _ENGINE, _SESSION_FACTORY
    _ENGINE = None
    _SESSION_FACTORY = None


@contextmanager
def session_scope() -> Iterator[Any]:
    """脚本与后台任务用的会话上下文：正常提交，异常回滚。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Any]:
    """FastAPI 依赖：路由只把会话传给服务层，不在路由里写 SQL。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database() -> dict:
    """返回 {connected, dialect, migration_revision, error?}，不抛异常。"""
    result: dict = {"connected": False, "dialect": None, "migration_revision": None}
    try:
        from sqlalchemy import text
    except ImportError:
        result["error"] = "SQLAlchemy 未安装，请执行 pip install -r requirements.txt"
        return result

    try:
        engine = get_engine()
        result["dialect"] = engine.dialect.name
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            try:
                revision = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            except Exception:
                revision = None
            result["migration_revision"] = revision
        result["connected"] = True
    except Exception as exc:  # 启动阶段不允许因为数据库问题崩溃
        result["error"] = str(exc)[:300]
    return result
