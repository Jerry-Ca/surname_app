"""迁徙事件与事件—证据关系（data-dictionary.md 第 2 节：migration_events、migration_event_evidences）。

事件必须有证据支持（evidence_codes 非空，由导入校验拦截）；
relation_type 在 CSV 未标注时留空，不允许后端替 B 猜“直接证据”。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..timeutil import utcnow
from .enums import CONFIDENCE, RELATION_STATUS, RELATION_TYPE, sql_in
from .evidence import Evidence
from .place import Place
from .surname import Surname


class MigrationEvent(Base):
    __tablename__ = "migration_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    migration_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    surname_id: Mapped[int] = mapped_column(ForeignKey("surnames.id", ondelete="RESTRICT"), index=True)
    # 地点允许为空：迁徙方向不明时只记 time_label，不强行补一个地点
    from_place_id: Mapped[int | None] = mapped_column(
        ForeignKey("places.id", ondelete="RESTRICT"), default=None
    )
    to_place_id: Mapped[int | None] = mapped_column(ForeignKey("places.id", ondelete="RESTRICT"), default=None)
    time_label: Mapped[str] = mapped_column(String(128))
    year_start: Mapped[int | None] = mapped_column(Integer, default=None)
    year_end: Mapped[int | None] = mapped_column(Integer, default=None)
    event_summary: Mapped[str] = mapped_column(Text)
    relation_status: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[str] = mapped_column(String(16))
    verified_by: Mapped[str] = mapped_column(String(32))
    verification_note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    from_place: Mapped[Place | None] = relationship(foreign_keys=[from_place_id], lazy="selectin")
    to_place: Mapped[Place | None] = relationship(foreign_keys=[to_place_id], lazy="selectin")
    surname: Mapped[Surname] = relationship(lazy="selectin")
    evidence_links: Mapped[list[MigrationEventEvidence]] = relationship(
        back_populates="migration_event", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "year_start IS NULL OR year_end IS NULL OR year_start <= year_end",
            name="ck_migration_events_year_range",
        ),
        CheckConstraint(f"relation_status IN {sql_in(RELATION_STATUS)}", name="ck_migration_events_relation_status"),
        CheckConstraint(f"confidence IN {sql_in(CONFIDENCE)}", name="ck_migration_events_confidence"),
        Index("ix_migration_events_surname", "surname_id", "year_start"),
    )


class MigrationEventEvidence(Base):
    __tablename__ = "migration_event_evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    migration_event_id: Mapped[int] = mapped_column(
        ForeignKey("migration_events.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidences.id", ondelete="CASCADE"), index=True)
    # 数据包未标注关系类型时留空（见 data-pipeline.md 第 3 节的 CSV 列约定）
    relation_type: Mapped[str | None] = mapped_column(String(16), default=None)

    migration_event: Mapped[MigrationEvent] = relationship(back_populates="evidence_links")
    evidence: Mapped[Evidence] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("migration_event_id", "evidence_id", name="uq_migration_event_evidences_pair"),
        CheckConstraint(
            f"relation_type IS NULL OR relation_type IN {sql_in(RELATION_TYPE)}",
            name="ck_migration_event_evidences_relation_type",
        ),
    )


