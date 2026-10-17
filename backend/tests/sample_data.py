"""测试用样例数据（只写入临时目录，不进入 data/）。

这些行的书名、卷次、原文都是**测试占位**，用来验证管线与接口形状，
不是任何历史事实（AGENTS.md 铁律 1）。字段值里明确写了“仅用于接口测试”。
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.db.session import get_session_factory
from app.services import ingestion

REGISTER_HEADER = [
    "source_code", "work_title", "work_author", "dynasty", "work_type", "edition",
    "publisher", "source_provider", "source_url", "license_status", "accessed_at",
    "content_hash", "notes",
]
EVIDENCE_HEADER = [
    "evidence_code", "surname", "evidence_type", "claim_text", "work_title", "work_author",
    "dynasty", "volume_or_section", "page_or_location", "original_excerpt", "source_code",
    "source_url", "access_note", "accessed_at", "verification_status", "confidence",
    "verified_by", "verification_note", "dispute_group", "year_start", "year_end", "time_label",
]
MIGRATION_HEADER = [
    "migration_code", "surname", "time_label", "year_start", "year_end", "from_historical_name",
    "from_modern_name", "from_location_status", "to_historical_name", "to_modern_name",
    "to_location_status", "event_summary", "relation_status", "confidence", "evidence_codes",
    "verified_by", "verification_note",
]
CORPUS_HEADER = [
    "search_code", "surname", "corpus_name", "query_text", "checked_at", "result_count",
    "no_result_reason", "operator", "note",
]


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig：与 data-pipeline.md 第 3 节一致（Windows 上 Excel 打开不乱码）
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})
    return path


def register_row(**overrides: str) -> dict[str, str]:
    row = {
        "source_code": "SRC-001",
        "work_title": "管线测试文献乙",
        "work_author": "测试编写者",
        "dynasty": "测试朝代",
        "work_type": "classic",
        "source_provider": "测试平台",
        "source_url": "https://example.org/item/1",
        "license_status": "public_domain",
        "accessed_at": "2026-10-17T03:21:00Z",
    }
    row.update(overrides)
    return row


def evidence_row(**overrides: str) -> dict[str, str]:
    row = {
        "evidence_code": "EV-LI-001",
        "surname": "李",
        "evidence_type": "earliest_attestation",
        "claim_text": "管线测试结论甲（仅用于接口测试，不代表历史事实）",
        "work_title": "管线测试文献乙",
        "work_author": "测试编写者",
        "volume_or_section": "卷一·测试篇",
        "page_or_location": "第 10 页",
        "original_excerpt": "管线测试原文摘录丙（仅用于接口测试）",
        "source_code": "SRC-001",
        "source_url": "https://example.org/item/1",
        "accessed_at": "2026-10-17T03:21:00Z",
        "verification_status": "verified",
        "confidence": "high",
        "verified_by": "B",
        "verification_note": "测试用核验说明：核对字段是否完整",
        "year_start": "-100",
        "year_end": "25",
        "time_label": "测试时间段表述",
    }
    row.update(overrides)
    return row


def migration_row(**overrides: str) -> dict[str, str]:
    row = {
        "migration_code": "MG-LI-001",
        "surname": "李",
        "time_label": "测试迁出时段",
        "year_start": "600",
        "year_end": "700",
        "from_historical_name": "测试原地名",
        "from_modern_name": "测试今地名甲",
        "from_location_status": "approximate",
        "to_historical_name": "测试迁入地名",
        "to_modern_name": "测试今地名乙",
        "to_location_status": "unlocatable",
        "event_summary": "管线测试迁徙概述（仅用于接口测试）",
        "relation_status": "agreed",
        "confidence": "medium",
        "evidence_codes": "EV-LI-001",
        "verified_by": "B",
        "verification_note": "测试用核验说明：确认证据编号可解析",
    }
    row.update(overrides)
    return row


def corpus_row(**overrides: str) -> dict[str, str]:
    row = {
        "search_code": "CS-LI-001",
        "surname": "李",
        "corpus_name": "测试语料甲",
        "query_text": "李",
        "checked_at": "2026-10-17T04:00:00Z",
        "result_count": "0",
        "no_result_reason": "测试语料中未检出该姓氏（仅用于接口测试）",
        "operator": "B",
    }
    row.update(overrides)
    return row


def build_repo(
    root: Path,
    *,
    sources: list[dict[str, str]] | None = None,
    evidences: list[dict[str, str]] | None = None,
    migrations: list[dict[str, str]] | None = None,
    corpus: list[dict[str, str]] | None = None,
) -> Path:
    """在临时目录里搭好 data/ 结构；只写传入的文件。"""
    (root / "data" / "verified").mkdir(parents=True, exist_ok=True)
    (root / "data" / "raw").mkdir(parents=True, exist_ok=True)
    if sources is not None:
        write_csv(root / "data" / "source_register.csv", REGISTER_HEADER, sources)
    if evidences is not None:
        write_csv(root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, evidences)
    if migrations is not None:
        write_csv(root / "data" / "verified" / "migrations.csv", MIGRATION_HEADER, migrations)
    if corpus is not None:
        write_csv(root / "data" / "corpus_searches.csv", CORPUS_HEADER, corpus)
    return root


def seed(root: Path) -> list:
    """按外键依赖顺序导入临时数据，返回每次导入的结果。"""
    order = [
        "data/source_register.csv",
        "data/corpus_searches.csv",
        "data/verified/evidences.csv",
        "data/verified/migrations.csv",
    ]
    outcomes = []
    session = get_session_factory()()
    try:
        for ref in order:
            if (root / ref).exists():
                outcomes.append(
                    ingestion.import_file(session, input_ref=ref, operator="B", stage="load", dry_run=False, root=root)
                )
    finally:
        session.close()
    return outcomes
