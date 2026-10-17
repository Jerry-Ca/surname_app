"""历史地点（data-dictionary.md 第 2 节：places）。

coordinates 只在 location_status=located 时才有值；unlocatable 必须为 NULL——
不伪造精确坐标是数据真实性的一部分（契约第 7 节）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..timeutil import utcnow
from .enums import LOCATION_STATUS, sql_in


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(primary_key=True)
    historical_name: Mapped[str] = mapped_column(String(128), index=True)
    modern_name: Mapped[str | None] = mapped_column(String(128), default=None)
    period: Mapped[str | None] = mapped_column(String(64), default=None)
    coordinates: Mapped[str | None] = mapped_column(String(64), default=None)
    location_status: Mapped[str] = mapped_column(String(16))
    location_note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint(f"location_status IN {sql_in(LOCATION_STATUS)}", name="ck_places_location_status"),
        CheckConstraint(
            "location_status <> 'unlocatable' OR coordinates IS NULL",
            name="ck_places_no_coordinates_when_unlocatable",
        ),
        Index("ix_places_name_period", "historical_name", "period"),
    )
