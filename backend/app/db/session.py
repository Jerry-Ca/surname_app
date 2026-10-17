"""数据库连接（C 主责）。

设计原则：任何数据库问题都不允许让应用启动失败。
连接不通时 /api/health 报 database_unavailable，其余接口按契约返回空结果或 503。
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings

_ENGINE: Any = None


def get_engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        from sqlalchemy import create_engine

        settings = get_settings()
        _ENGINE = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    return _ENGINE


def reset_engine() -> None:
    """测试用：强制下次调用重新建引擎。"""
    global _ENGINE
    _ENGINE = None


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
