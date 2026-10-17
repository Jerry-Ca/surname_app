"""契约公共对象的序列化（docs/api-contract.md 第 2 节）。

放在单独模块的唯一理由：`SourceRef` / `EvidenceSummary` / `PlaceRef` 的字段列表
只能有一份。查询接口（queries.py）与检索服务（search.py）都从这里取，
否则某次改动只改一处，前端就会拿到两种形状的“同一个对象”。
"""

from __future__ import annotations

from ..models import Evidence
from ..timeutil import to_iso8601


def source_ref(link) -> dict:
    """`SourceRef`（契约 2.1）：一条证据引用某个来源版本的完整信息。"""
    edition = link.source_edition
    work = edition.work
    return {
        "source_code": edition.source_code,
        "work_title": work.title,
        "work_author": work.author,
        "dynasty": work.dynasty,
        "work_type": work.work_type,
        "edition": edition.edition,
        "volume_or_section": link.evidence.volume_or_section,
        "page_or_location": link.page_or_location,
        "source_provider": edition.source_provider,
        "source_url": edition.source_url,
        "accessed_at": to_iso8601(edition.accessed_at),
        "license_status": edition.license_status,
        "link_status": edition.link_status,
        "support_type": link.support_type,
    }


def evidence_summary(evidence: Evidence) -> dict:
    """`EvidenceSummary`（契约 2.2）：列表与卡片用的证据摘要。"""
    return {
        "evidence_code": evidence.evidence_code,
        "evidence_type": evidence.evidence_type,
        "claim_text": evidence.claim_text,
        "original_excerpt": evidence.original_excerpt,
        "volume_or_section": evidence.volume_or_section,
        "year_start": evidence.year_start,
        "year_end": evidence.year_end,
        "time_label": evidence.time_label,
        "verification_status": evidence.verification_status,
        "confidence": evidence.confidence,
        "sources": [source_ref(link) for link in evidence.sources],
    }


def place_ref(place) -> dict | None:
    """`PlaceRef`（契约 2.4）；没有地点记录时返回 null，不编造坐标。"""
    if place is None:
        return None
    return {
        "historical_name": place.historical_name,
        "modern_name": place.modern_name,
        "period": place.period,
        "location_status": place.location_status,
        "coordinates": place.coordinates,
        "location_note": place.location_note,
    }
