"""0001 initial schema：按 data-dictionary.md 第 2 节建齐全部表

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-17

内容纯结构，不含任何数据（数据一律走 scripts/import_data.py）。
枚举取值以 app/models/enums.py 为准，该文件与 data-dictionary.md 第 3 节逐条对应。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------------------------------------------------------- 姓氏
    op.create_table(
        "surnames",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("category IN ('single', 'compound')", name="ck_surnames_category"),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_surnames_status"),
    )
    op.create_index("ix_surnames_canonical_name", "surnames", ["canonical_name"], unique=True)

    op.create_table(
        "surname_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("surname_id", sa.Integer(), nullable=False),
        sa.Column("alias_name", sa.String(length=32), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["surname_id"], ["surnames.id"], name="fk_surname_aliases_surname_id", ondelete="CASCADE"),
        sa.UniqueConstraint("surname_id", "alias_name", name="uq_surname_aliases_name"),
        sa.CheckConstraint(
            "alias_type IN ('variant', 'honorific', 'traditional_simplified', 'other')",
            name="ck_surname_aliases_type",
        ),
    )
    op.create_index("ix_surname_aliases_surname_id", "surname_aliases", ["surname_id"])

    # ---------------------------------------------------------------- 文献
    op.create_table(
        "source_works",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False),
        sa.Column("dynasty", sa.String(length=64), nullable=True),
        sa.Column("work_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "work_type IN ('official_history', 'surname_book', 'local_gazetteer', 'classic', 'other')",
            name="ck_source_works_type",
        ),
    )
    op.create_index("ix_source_works_title", "source_works", ["title"])
    op.create_index("ix_source_works_title_author", "source_works", ["title", "author"])

    op.create_table(
        "source_editions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("source_code", sa.String(length=16), nullable=False),
        sa.Column("edition", sa.String(length=128), nullable=True),
        sa.Column("publisher", sa.String(length=128), nullable=True),
        sa.Column("source_provider", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license_status", sa.String(length=32), nullable=False),
        sa.Column("link_status", sa.String(length=16), nullable=False),
        sa.Column("accessed_at", sa.DateTime(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["work_id"], ["source_works.id"], name="fk_source_editions_work_id", ondelete="RESTRICT"),
        sa.CheckConstraint(
            "license_status IN ('public_domain', 'platform_terms_ok', 'restricted_excerpt_only', 'unknown')",
            name="ck_source_editions_license",
        ),
        sa.CheckConstraint("link_status IN ('ok', 'stale')", name="ck_source_editions_link_status"),
    )
    op.create_index("ix_source_editions_work_id", "source_editions", ["work_id"])
    op.create_index("ix_source_editions_source_code", "source_editions", ["source_code"], unique=True)

    # ---------------------------------------------------------------- 地点
    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("historical_name", sa.String(length=128), nullable=False),
        sa.Column("modern_name", sa.String(length=128), nullable=True),
        sa.Column("period", sa.String(length=64), nullable=True),
        sa.Column("coordinates", sa.String(length=64), nullable=True),
        sa.Column("location_status", sa.String(length=16), nullable=False),
        sa.Column("location_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "location_status IN ('located', 'approximate', 'unlocatable')", name="ck_places_location_status"
        ),
        sa.CheckConstraint(
            "location_status <> 'unlocatable' OR coordinates IS NULL", name="ck_places_no_coordinates_when_unlocatable"
        ),
    )
    op.create_index("ix_places_historical_name", "places", ["historical_name"])
    op.create_index("ix_places_name_period", "places", ["historical_name", "period"])

    # ---------------------------------------------------------------- 证据
    op.create_table(
        "evidences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_code", sa.String(length=32), nullable=False),
        sa.Column("surname_id", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("original_excerpt", sa.Text(), nullable=False),
        sa.Column("volume_or_section", sa.String(length=256), nullable=False),
        sa.Column("time_label", sa.String(length=128), nullable=True),
        sa.Column("year_start", sa.Integer(), nullable=True),
        sa.Column("year_end", sa.Integer(), nullable=True),
        sa.Column("verification_status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("verified_by", sa.String(length=32), nullable=False),
        sa.Column("verification_note", sa.Text(), nullable=False),
        sa.Column("dispute_group", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["surname_id"], ["surnames.id"], name="fk_evidences_surname_id", ondelete="RESTRICT"),
        sa.CheckConstraint(
            "year_start IS NULL OR year_end IS NULL OR year_start <= year_end", name="ck_evidences_year_range"
        ),
        sa.CheckConstraint(
            "verification_status <> 'disputed' OR dispute_group IS NOT NULL", name="ck_evidences_disputed_group"
        ),
        sa.CheckConstraint(
            "evidence_type IN ('earliest_attestation', 'commandery', 'migration', 'other')", name="ck_evidences_type"
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'disputed', 'link_stale', 'retracted')",
            name="ck_evidences_status",
        ),
        sa.CheckConstraint("confidence IN ('high', 'medium', 'low')", name="ck_evidences_confidence"),
    )
    op.create_index("ix_evidences_evidence_code", "evidences", ["evidence_code"], unique=True)
    op.create_index("ix_evidences_surname_id", "evidences", ["surname_id"])
    op.create_index("ix_evidences_verification_status", "evidences", ["verification_status"])
    op.create_index("ix_evidences_dispute_group", "evidences", ["dispute_group"])
    op.create_index("ix_evidences_surname_type_status", "evidences", ["surname_id", "evidence_type", "verification_status"])

    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("source_edition_id", sa.Integer(), nullable=False),
        sa.Column("citation_detail", sa.Text(), nullable=True),
        sa.Column("page_or_location", sa.String(length=128), nullable=True),
        sa.Column("support_type", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidences.id"], name="fk_evidence_sources_evidence_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_edition_id"], ["source_editions.id"], name="fk_evidence_sources_source_edition_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("evidence_id", "source_edition_id", name="uq_evidence_sources_pair"),
        sa.CheckConstraint(
            "support_type IS NULL OR support_type IN ('direct', 'circumstantial', 'genealogy')",
            name="ck_evidence_sources_support_type",
        ),
    )
    op.create_index("ix_evidence_sources_evidence_id", "evidence_sources", ["evidence_id"])
    op.create_index("ix_evidence_sources_source_edition_id", "evidence_sources", ["source_edition_id"])

    # ---------------------------------------------------------------- 迁徙
    op.create_table(
        "migration_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("migration_code", sa.String(length=32), nullable=False),
        sa.Column("surname_id", sa.Integer(), nullable=False),
        sa.Column("from_place_id", sa.Integer(), nullable=True),
        sa.Column("to_place_id", sa.Integer(), nullable=True),
        sa.Column("time_label", sa.String(length=128), nullable=False),
        sa.Column("year_start", sa.Integer(), nullable=True),
        sa.Column("year_end", sa.Integer(), nullable=True),
        sa.Column("event_summary", sa.Text(), nullable=False),
        sa.Column("relation_status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("verified_by", sa.String(length=32), nullable=False),
        sa.Column("verification_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["surname_id"], ["surnames.id"], name="fk_migration_events_surname_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["from_place_id"], ["places.id"], name="fk_migration_events_from_place_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_place_id"], ["places.id"], name="fk_migration_events_to_place_id", ondelete="RESTRICT"),
        sa.CheckConstraint(
            "year_start IS NULL OR year_end IS NULL OR year_start <= year_end", name="ck_migration_events_year_range"
        ),
        sa.CheckConstraint("relation_status IN ('agreed', 'disputed', 'unclear')", name="ck_migration_events_relation_status"),
        sa.CheckConstraint("confidence IN ('high', 'medium', 'low')", name="ck_migration_events_confidence"),
    )
    op.create_index("ix_migration_events_migration_code", "migration_events", ["migration_code"], unique=True)
    op.create_index("ix_migration_events_surname_id", "migration_events", ["surname_id"])
    op.create_index("ix_migration_events_surname", "migration_events", ["surname_id", "year_start"])

    op.create_table(
        "migration_event_evidences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("migration_event_id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["migration_event_id"], ["migration_events.id"], name="fk_migration_event_evidences_event_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["evidences.id"], name="fk_migration_event_evidences_evidence_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("migration_event_id", "evidence_id", name="uq_migration_event_evidences_pair"),
        sa.CheckConstraint(
            "relation_type IS NULL OR relation_type IN ('direct', 'circumstantial', 'genealogy', 'conflicting')",
            name="ck_migration_event_evidences_relation_type",
        ),
    )
    op.create_index("ix_migration_event_evidences_migration_event_id", "migration_event_evidences", ["migration_event_id"])
    op.create_index("ix_migration_event_evidences_evidence_id", "migration_event_evidences", ["evidence_id"])

    # ---------------------------------------------------------------- 语料审计 / 审核 / 向量 / 导入任务
    op.create_table(
        "corpus_searches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_code", sa.String(length=32), nullable=False),
        sa.Column("surname_id", sa.Integer(), nullable=False),
        sa.Column("corpus_name", sa.String(length=128), nullable=False),
        sa.Column("query_text", sa.String(length=256), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("no_result_reason", sa.Text(), nullable=True),
        sa.Column("operator", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["surname_id"], ["surnames.id"], name="fk_corpus_searches_surname_id", ondelete="RESTRICT"),
        sa.CheckConstraint("result_count <> 0 OR no_result_reason IS NOT NULL", name="ck_corpus_searches_empty_reason"),
    )
    op.create_index("ix_corpus_searches_search_code", "corpus_searches", ["search_code"], unique=True)
    op.create_index("ix_corpus_searches_surname_id", "corpus_searches", ["surname_id"])
    op.create_index("ix_corpus_searches_surname", "corpus_searches", ["surname_id", "checked_at"])

    op.create_table(
        "review_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reviewer", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_review_logs_target", "review_logs", ["target_type", "target_id"])

    op.create_table(
        "embedding_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("embedding_vector", sa.JSON(), nullable=True),
        sa.Column("dimensions", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidences.id"], name="fk_embedding_chunks_evidence_id", ondelete="CASCADE"),
    )
    op.create_index("ix_embedding_chunks_evidence_id", "embedding_chunks", ["evidence_id"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=256), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("input_ref", sa.Text(), nullable=False),
        sa.Column("operator", sa.String(length=32), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("rolled_back", sa.Boolean(), nullable=False),
        sa.Column("error_log", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("stage IN ('fetch', 'clean', 'verify', 'load', 'index')", name="ck_ingestion_jobs_stage"),
    )
    op.create_index("ix_ingestion_jobs_job_id", "ingestion_jobs", ["job_id"], unique=True)


def downgrade() -> None:
    # 反序删除，先删被引用的表的“引用方”
    op.drop_table("ingestion_jobs")
    op.drop_table("embedding_chunks")
    op.drop_table("review_logs")
    op.drop_table("corpus_searches")
    op.drop_table("migration_event_evidences")
    op.drop_table("migration_events")
    op.drop_table("evidence_sources")
    op.drop_table("evidences")
    op.drop_table("places")
    op.drop_table("source_editions")
    op.drop_table("source_works")
    op.drop_table("surname_aliases")
    op.drop_table("surnames")