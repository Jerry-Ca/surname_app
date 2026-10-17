"""文献作品与具体版本（data-dictionary.md 第 2 节：source_works、source_editions）。

事实与证据分离的第一层：作品是书名/作者/朝代，版本是平台、链接、授权与访问时间。
一条事实可挂多个版本，一个版本可支持多条事实。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..timeutil import utcnow
from .enums import LICENSE_STATUS, LINK_STATUS, WORK_TYPE, sql_in


class SourceWork(Base):
    __tablename__ = "source_works"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), index=True)
    author: Mapped[str] = mapped_column(String(128))
    dynasty: Mapped[str | None] = mapped_column(String(64), default=None)
    work_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    editions: Mapped[list[SourceEdition]] = relationship(back_populates="work")

    __table_args__ = (
        Index("ix_source_works_title_author", "title", "author"),
        CheckConstraint(f"work_type IN {sql_in(WORK_TYPE)}", name="ck_source_works_type"),
    )


class SourceEdition(Base):
    __tablename__ = "source_editions"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("source_works.id", ondelete="RESTRICT"), index=True)
    source_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    edition: Mapped[str | None] = mapped_column(String(128), default=None)
    publisher: Mapped[str | None] = mapped_column(String(128), default=None)
    source_provider: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text, default=None)
    license_status: Mapped[str] = mapped_column(String(32))
    link_status: Mapped[str] = mapped_column(String(16), default="ok")
    accessed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    content_hash: Mapped[str | None] = mapped_column(String(128), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    work: Mapped[SourceWork] = relationship(back_populates="editions", lazy="selectin")

    __table_args__ = (
        CheckConstraint(f"license_status IN {sql_in(LICENSE_STATUS)}", name="ck_source_editions_license"),
        CheckConstraint(f"link_status IN {sql_in(LINK_STATUS)}", name="ck_source_editions_link_status"),
    )
