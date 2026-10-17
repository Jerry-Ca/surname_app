"""SQLite 表结构与枚举的唯一来源（执行清单 §一.3、§一.4）。

谁都不许在别处再写一遍列名或枚举：init_db.py、import_data.py、validate_package.py、
app/* 全部从这里取，避免"库里一个写法、接口里另一个写法"。

字段命名的取舍（需 A 在 api-contract-v1 里确认）：
  - 执行清单要求 evidences 自带 source_title / source_url（原文字段与来源同表），
    因此这里不再建 evidence_sources 关系表；
  - 编号字段叫 evidence_id，与旧的 data-dictionary 里的 evidence_code 是同一个东西，
    只在新路线里统一用 evidence_id（冲突已提请 A 裁决，见任务卡 C-08）。
"""

from __future__ import annotations

# 证据的核对状态（执行清单 §一.4 的五值，代码值 ↔ 界面中文见 docs/data-dictionary.md 第 3.1 节）
VERIFICATION_STATUS = ("pending", "verified", "disputed", "link_stale", "retracted")
VERIFICATION_STATUS_LABELS = {
    "pending": "待核对",
    "verified": "已核对",
    "disputed": "有争议",
    "link_stale": "链接待复查",
    "retracted": "已撤回",
}
# 前端可见的状态：pending 不外发（数据字典第 7 节）
PUBLISHABLE_STATUS = ("verified", "disputed", "link_stale", "retracted")

EVIDENCE_TYPE = ("earliest_attestation", "commandery", "migration", "other")
CONFIDENCE = ("high", "medium", "low")
RELATION_STATUS = ("agreed", "disputed", "unclear")
LOCATION_STATUS = ("located", "approximate", "unlocatable")
WORK_TYPE = ("official_history", "surname_book", "local_gazetteer", "classic", "other")
LICENSE_STATUS = ("public_domain", "platform_terms_ok", "restricted_excerpt_only", "unknown")
ALIAS_TYPE = ("variant", "honorific", "traditional_simplified", "other")
SURNAME_CATEGORY = ("single", "compound")

# 编号规则（数据字典第 4 节）：一旦生成不得回收、不得复用
CODE_PATTERNS = {
    "evidence_id": r"^EV-[A-Z-]+-\d{3}$",
    "migration_code": r"^MG-[A-Z-]+-\d{3}$",
    "search_code": r"^CS-[A-Z-]+-\d{3}$",
    "source_code": r"^SRC-\d{3}$",
}

# 各表允许的最大文本长度（与 CREATE TABLE 里的声明一致；超长在别的库里会被拒，这里提前拦）
MAX_LENGTHS = {
    "surnames": {"name": 32, "pinyin": 64, "description": 2000},
    "source_works": {
        "source_code": 16, "title": 256, "author": 128, "dynasty": 64, "work_type": 32,
        "edition": 128, "source_provider": 128, "license_status": 32, "content_hash": 128,
    },
    "evidences": {
        "evidence_id": 32, "claim_text": 2000, "original_excerpt": 2000, "volume_or_section": 256,
        "page_or_location": 128, "source_title": 256, "source_url": 500, "time_label": 128,
        "verified_by": 32, "dispute_group": 64,
    },
    "places": {"historical_name": 128, "modern_name": 128, "period": 64, "coordinates": 64},
    "migration_events": {"migration_code": 32, "time_label": 128, "event_summary": 2000, "verified_by": 32},
    "corpus_searches": {"search_code": 32, "corpus_name": 128, "query_text": 256, "operator": 32},
}

# 表结构：只用 sqlite3 能理解的语法；CHECK 约束就是执行清单要求的"设置约束"
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS surnames (
        id            INTEGER PRIMARY KEY,
        name          TEXT    NOT NULL UNIQUE,
        category      TEXT    NOT NULL DEFAULT 'single' CHECK (category IN ('single', 'compound')),
        pinyin        TEXT,
        status        TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
        description   TEXT,
        created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS surname_aliases (
        id            INTEGER PRIMARY KEY,
        surname_id    INTEGER NOT NULL REFERENCES surnames(id) ON DELETE CASCADE,
        alias_name    TEXT    NOT NULL,
        alias_type    TEXT    NOT NULL CHECK (alias_type IN ('variant', 'honorific', 'traditional_simplified', 'other')),
        note          TEXT,
        UNIQUE (surname_id, alias_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_works (
        id              INTEGER PRIMARY KEY,
        source_code     TEXT    NOT NULL UNIQUE,
        title           TEXT    NOT NULL,
        author          TEXT    NOT NULL,
        dynasty         TEXT,
        work_type       TEXT    NOT NULL CHECK (work_type IN ('official_history', 'surname_book', 'local_gazetteer', 'classic', 'other')),
        edition         TEXT,
        source_provider TEXT,
        source_url      TEXT,
        license_status  TEXT    NOT NULL CHECK (license_status IN ('public_domain', 'platform_terms_ok', 'restricted_excerpt_only', 'unknown')),
        accessed_at     TEXT,
        content_hash    TEXT,
        notes           TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidences (
        id                  INTEGER PRIMARY KEY,
        evidence_id         TEXT    NOT NULL UNIQUE,
        surname_id          INTEGER NOT NULL REFERENCES surnames(id) ON DELETE RESTRICT,
        evidence_type       TEXT    NOT NULL CHECK (evidence_type IN ('earliest_attestation', 'commandery', 'migration', 'other')),
        claim_text          TEXT    NOT NULL,
        original_excerpt    TEXT    NOT NULL,
        volume_or_section   TEXT    NOT NULL,
        page_or_location    TEXT,
        source_code         TEXT    REFERENCES source_works(source_code) ON DELETE RESTRICT,
        source_title        TEXT    NOT NULL,
        source_url          TEXT    NOT NULL,
        year_start          INTEGER,
        year_end            INTEGER,
        time_label          TEXT,
        verification_status TEXT    NOT NULL CHECK (verification_status IN ('pending', 'verified', 'disputed', 'link_stale', 'retracted')),
        confidence          TEXT    NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
        verified_by         TEXT,
        verification_note   TEXT,
        dispute_group       TEXT,
        created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        -- 必填三件套（执行清单 §一.4）：空原文、空来源、空链接都不允许
        CHECK (length(trim(original_excerpt)) > 0),
        CHECK (length(trim(source_title)) > 0),
        CHECK (length(trim(source_url)) > 0),
        CHECK (year_start IS NULL OR year_end IS NULL OR year_start <= year_end),
        CHECK (verification_status <> 'disputed' OR (dispute_group IS NOT NULL AND length(trim(dispute_group)) > 0))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS places (
        id              INTEGER PRIMARY KEY,
        historical_name TEXT    NOT NULL,
        modern_name     TEXT,
        period          TEXT,
        location_status TEXT    NOT NULL CHECK (location_status IN ('located', 'approximate', 'unlocatable')),
        coordinates     TEXT,
        location_note   TEXT,
        CHECK (location_status <> 'unlocatable' OR coordinates IS NULL)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS migration_events (
        id                INTEGER PRIMARY KEY,
        migration_code    TEXT    NOT NULL UNIQUE,
        surname_id        INTEGER NOT NULL REFERENCES surnames(id) ON DELETE RESTRICT,
        from_place_id     INTEGER REFERENCES places(id) ON DELETE RESTRICT,
        to_place_id       INTEGER REFERENCES places(id) ON DELETE RESTRICT,
        time_label        TEXT    NOT NULL,
        year_start        INTEGER,
        year_end          INTEGER,
        event_summary     TEXT    NOT NULL,
        relation_status   TEXT    NOT NULL CHECK (relation_status IN ('agreed', 'disputed', 'unclear')),
        confidence        TEXT    NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
        verified_by       TEXT,
        verification_note TEXT,
        created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        CHECK (year_start IS NULL OR year_end IS NULL OR year_start <= year_end)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS migration_event_evidences (
        id                 INTEGER PRIMARY KEY,
        migration_event_id INTEGER NOT NULL REFERENCES migration_events(id) ON DELETE CASCADE,
        evidence_id        TEXT    NOT NULL REFERENCES evidences(evidence_id) ON DELETE CASCADE,
        relation_type      TEXT,
        UNIQUE (migration_event_id, evidence_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corpus_searches (
        id               INTEGER PRIMARY KEY,
        search_code      TEXT    NOT NULL UNIQUE,
        surname_id       INTEGER NOT NULL REFERENCES surnames(id) ON DELETE RESTRICT,
        corpus_name      TEXT    NOT NULL,
        query_text       TEXT    NOT NULL,
        checked_at       TEXT    NOT NULL,
        result_count     INTEGER NOT NULL,
        no_result_reason TEXT,
        operator         TEXT    NOT NULL,
        note             TEXT,
        CHECK (result_count >= 0),
        CHECK (result_count <> 0 OR (no_result_reason IS NOT NULL AND length(trim(no_result_reason)) > 0))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_logs (
        id          INTEGER PRIMARY KEY,
        target_type TEXT    NOT NULL,
        target_id   TEXT    NOT NULL,
        action      TEXT    NOT NULL,
        reviewer    TEXT    NOT NULL,
        before_json TEXT,
        after_json  TEXT,
        review_note TEXT,
        created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingestion_jobs (
        id          INTEGER PRIMARY KEY,
        job_id      TEXT    NOT NULL UNIQUE,
        source      TEXT    NOT NULL,
        input_ref   TEXT    NOT NULL,
        operator    TEXT    NOT NULL,
        total       INTEGER NOT NULL DEFAULT 0,
        accepted    INTEGER NOT NULL DEFAULT 0,
        rejected    INTEGER NOT NULL DEFAULT 0,
        rolled_back INTEGER NOT NULL DEFAULT 0,
        error_json  TEXT,
        started_at  TEXT    NOT NULL,
        finished_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_evidences_surname ON evidences (surname_id, evidence_type, verification_status)",
    "CREATE INDEX IF NOT EXISTS ix_evidences_status ON evidences (verification_status)",
    "CREATE INDEX IF NOT EXISTS ix_evidences_dispute ON evidences (dispute_group)",
    "CREATE INDEX IF NOT EXISTS ix_corpus_searches_surname ON corpus_searches (surname_id, checked_at)",
    "CREATE INDEX IF NOT EXISTS ix_migration_events_surname ON migration_events (surname_id, year_start)",
    "CREATE INDEX IF NOT EXISTS ix_surname_aliases_name ON surname_aliases (alias_name)",
)

# FTS5 可用时建立的全文索引（不可用就回落 LIKE，见 app/search.py）。
# 必须用 trigram 分词器：默认的 unicode61 把一整段连续汉字当成一个词，「陇西」在「陇西郡望」里匹配不到。
FTS_STATEMENTS: tuple[str, ...] = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS evidences_fts USING fts5("
    "evidence_id UNINDEXED, claim_text, original_excerpt, volume_or_section, tokenize='trigram')",
)

TABLES = (
    "surnames", "surname_aliases", "source_works", "evidences", "places",
    "migration_events", "migration_event_evidences", "corpus_searches",
    "review_logs", "ingestion_jobs",
)
