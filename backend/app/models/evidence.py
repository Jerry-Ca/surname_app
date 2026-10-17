"""原子证据与证据—来源关系（data-dictionary.md 第 2 节：evidences、evidence_sources）。

一行证据就是一条可单独核验的事实：claim_text 是结论，original_excerpt 是原文，
两者必须同时存在——只有原文没有结论无法展示，只有结论没有原文无法核验。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..timeutil import utcnow
from .enums import CONFIDENCE, EVIDENCE_TYPE, SUPPORT_TYPE, VERIFICATION_STATUS, sql_in
from .source import SourceEdition


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    surname_id: Mapped[int] = mapped_column(ForeignKey("surnames.id", ondelete="RESTRICT"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32))
    claim_text: Mapped[str] = mapped_column(Text)
    original_excerpt: Mapped[str] = mapped_column(Text)
    volume_or_section: Mapped[str] = mapped_column(String(256))
    time_label: Mapped[str | None] = mapped_column(String(128), default=None)
    year_start: Mapped[int | None] = mapped_column(Integer, default=None)
    year_end: Mapped[int | None] = mapped_column(Integer, default=None)
    verification_status: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[str] = mapped_column(String(16))
    verified_by: Mapped[str] = mapped_column(String(32))
    verification_note: Mapped[str] = mapped_column(Text)
    dispute_group: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sources: Mapped[list[EvidenceSource]] = relationship(
        back_populates="evidence", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        # 不确定的年代必须留空并写 time_label，不允许为了让排序好看而补一个年份
        CheckConstraint(
            "year_start IS NULL OR year_end IS NULL OR year_start <= year_end",
            name="ck_evidences_year_range",
        ),
        # disputed 必须有 dispute_group，否则并列展示会丢组
        CheckConstraint(
            "verification_status <> 'disputed' OR dispute_group IS NOT NULL",
            name="ck_evidences_disputed_group",
        ),
        CheckConstraint(f"evidence_type IN {sql_in(EVIDENCE_TYPE)}", name="ck_evidences_type"),
        CheckConstraint(f"verification_status IN {sql_in(VERIFICATION_STATUS)}", name="ck_evidences_status"),
        CheckConstraint(f"confidence IN {sql_in(CONFIDENCE)}", name="ck_evidences_confidence"),
        Index("ix_evidences_surname_type_status", "surname_id", "evidence_type", "verification_status"),
    )


class EvidenceSource(Base):
    """证据与来源版本的连接表（多对多关系的实体，带引用细节）。"""

    __tablename__ = "evidence_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidences.id", ondelete="CASCADE"), index=True)
    source_edition_id: Mapped[int] = mapped_column(
        ForeignKey("source_editions.id", ondelete="RESTRICT"), index=True
    )
    citation_detail: Mapped[str | None] = mapped_column(Text, default=None)
    page_or_location: Mapped[str | None] = mapped_column(String(128), default=None)
    # CSV 暂未提供支持方式与关系类型，留空表示“数据包未标注”，不猜默认值
    support_type: Mapped[str | None] = mapped_column(String(16), default=None)

    evidence: Mapped[Evidence] = relationship(back_populates="sources")
    source_edition: Mapped[SourceEdition] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("evidence_id", "source_edition_id", name="uq_evidence_sources_pair"),
        CheckConstraint(
            f"support_type IS NULL OR support_type IN {sql_in(SUPPORT_TYPE)}",
            name="ck_evidence_sources_support_type",
        ),
    )
