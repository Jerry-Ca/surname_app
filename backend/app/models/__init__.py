"""ORM 模型（C 主责，任务 C-02）。

表与字段的唯一依据是 ../../docs/data-dictionary.md 第 2 节。
约束：任何表结构变更都必须通过 migrations/ 下的 Alembic 迁移完成，
不允许在代码里 create_all（AGENTS.md 铁律 5）。

各模块的对应关系：
    surname.py           surnames / surname_aliases
    source.py            source_works / source_editions
    evidence.py          evidences / evidence_sources
    place.py             places
    migration_event.py   migration_events / migration_event_evidences
    audit.py             corpus_searches / review_logs / embedding_chunks / ingestion_jobs
"""

from __future__ import annotations

from .audit import CorpusSearch, EmbeddingChunk, IngestionJob, ReviewLog
from .evidence import Evidence, EvidenceSource
from .migration_event import MigrationEvent, MigrationEventEvidence
from .place import Place
from .source import SourceEdition, SourceWork
from .surname import Surname, SurnameAlias

__all__ = [
    "CorpusSearch",
    "EmbeddingChunk",
    "Evidence",
    "EvidenceSource",
    "IngestionJob",
    "MigrationEvent",
    "MigrationEventEvidence",
    "Place",
    "ReviewLog",
    "SourceEdition",
    "SourceWork",
    "Surname",
    "SurnameAlias",
]
