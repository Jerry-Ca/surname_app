"""ORM 基类（任务 C-02）。

表结构的唯一依据是 ../../docs/data-dictionary.md 第 2 节；
任何表结构变更只能通过 migrations/ 下的 Alembic 迁移完成（AGENTS.md 铁律 5）。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全部 ORM 模型的基类，Base.metadata 是迁移比对的唯一目标。"""


def import_models() -> None:
    """导入全部模型模块，使 Base.metadata 完整。

    迁移脚本（migrations/env.py）与建表检查都依赖这一步：
    只 import Base 不会触发各模型模块执行，metadata 里就会缺表。
    """
    from .. import models  # noqa: F401  # 仅为注册副作用
