"""姓氏与别名（data-dictionary.md 第 2 节：surnames、surname_aliases）。

一条姓氏只允许一个主记录；繁简、异体、氏称全部放 surname_aliases，
匹配时由 app/services/search.py 按别名回落到主记录。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..timeutil import utcnow
from .enums import ALIAS_TYPE, SURNAME_CATEGORY, SURNAME_STATUS, sql_in


class Surname(Base):
    __tablename__ = "surnames"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(16), default="single")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    aliases: Mapped[list[SurnameAlias]] = relationship(
        back_populates="surname", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(f"category IN {sql_in(SURNAME_CATEGORY)}", name="ck_surnames_category"),
        CheckConstraint(f"status IN {sql_in(SURNAME_STATUS)}", name="ck_surnames_status"),
    )


class SurnameAlias(Base):
    __tablename__ = "surname_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    surname_id: Mapped[int] = mapped_column(ForeignKey("surnames.id", ondelete="CASCADE"), index=True)
    alias_name: Mapped[str] = mapped_column(String(32))
    alias_type: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, default=None)

    surname: Mapped[Surname] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("surname_id", "alias_name", name="uq_surname_aliases_name"),
        CheckConstraint(f"alias_type IN {sql_in(ALIAS_TYPE)}", name="ck_surname_aliases_type"),
    )
