"""语料审计、审核日志、向量片段与导入任务（data-dictionary.md 第 2 节的后四张表）。

这四张表是“可追溯”的载体：
  - corpus_searches：查过哪些语料、查到几条、没有结果的原因（未收录页面直接展示它）
  - review_logs：谁在什么时候改了什么、为什么
  - embedding_chunks：向量片段（pgvector 不可用时用 JSON 列降级存储）
  - ingestion_jobs：每次导入的统计与错误明细
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..timeutil import utcnow
from .enums import INGESTION_STAGE, sql_in
from .surname import Surname


class CorpusSearch(Base):
    __tablename__ = "corpus_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    surname_id: Mapped[int] = mapped_column(ForeignKey("surnames.id", ondelete="RESTRICT"), index=True)
    corpus_name: Mapped[str] = mapped_column(String(128))
    query_text: Mapped[str] = mapped_column(String(256))
    checked_at: Mapped[datetime] = mapped_column(DateTime)
    result_count: Mapped[int] = mapped_column(Integer)
    no_result_reason: Mapped[str | None] = mapped_column(Text, default=None)
    operator: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, default=None)

    surname: Mapped[Surname] = relationship(lazy="selectin")

    __table_args__ = (
        # 结果为 0 时必须写明原因，否则“查过没有”无法与“没查”区分
        CheckConstraint(
            "result_count <> 0 OR no_result_reason IS NOT NULL",
            name="ck_corpus_searches_empty_reason",
        ),
        Index("ix_corpus_searches_surname", "surname_id", "checked_at"),
    )


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    reviewer: Mapped[str] = mapped_column(String(32))
    before_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    after_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    review_note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_review_logs_target", "target_type", "target_id"),)


class EmbeddingChunk(Base):
    __tablename__ = "embedding_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidences.id", ondelete="CASCADE"), index=True)
    chunk_text: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    # 不用 pgvector：扩展装不上时用 JSON 列 + 应用层相似度，保证核心功能不被阻塞
    embedding_vector: Mapped[list[float] | None] = mapped_column(JSON, default=None)
    dimensions: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(256))
    stage: Mapped[str] = mapped_column(String(16))
    input_ref: Mapped[str] = mapped_column(Text)
    operator: Mapped[str] = mapped_column(String(32))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False)
    error_log: Mapped[list | None] = mapped_column(JSON, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    __table_args__ = (CheckConstraint(f"stage IN {sql_in(INGESTION_STAGE)}", name="ck_ingestion_jobs_stage"),)
