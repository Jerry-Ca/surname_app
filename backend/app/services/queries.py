"""查询服务（任务 C-04）：把库里的证据拼成契约第 4—7 节的响应。

三条贯穿全文件的规则（都来自文档，不是实现偏好）：
  1. `pending` 状态的数据**不返回给前端**（data-dictionary.md 第 7 节）
  2. `retracted`（已撤回）保留并返回，但不得作为结论参与排序（契约第 5 节）
  3. 任何“查不到”都返回空结构 + coverage 说明，不是错误（契约第 1.1 节）

字段名与形状只能来自 docs/api-contract.md；本模块不做任何字段改名或临时字段。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CorpusSearch,
    Evidence,
    MigrationEvent,
    Surname,
)
from ..timeutil import to_iso8601
from .search import SurnameMatch, resolve_surname

# 契约第 1.1 节：语料中查不到时前端展示的固定文案
ABSTAIN_TEXT = "当前资料不足以确认"

# 前端可见的状态：pending 不进列表，retracted 进列表但不作为结论
VISIBLE_STATUSES = ("verified", "disputed", "link_stale", "retracted")

# 最早书证的排序依据（契约第 5 节要求把这个规则一并返回）
SORT_RULE = "verified_first_then_year_start"
SORT_NOTE = (
    "先排有年代记录的：按已核对优先、year_start 升序；无 year_start 的记录排在最后并单独标注"
    "（返回项里 year_start 为 null、时间表述见 time_label）；"
    "已撤回（retracted）的记录不参与排序，列在 sort_basis.excluded 中"
)


def _visible_filter():
    return Evidence.verification_status.in_(VISIBLE_STATUSES)


def _status_priority(status: str) -> int:
    """已核对优先；其余按状态固定次序，保证分页稳定。"""
    order = {"verified": 0, "disputed": 1, "link_stale": 2, "retracted": 3}
    return order.get(status, 9)


def _counts(session: Session, surname: Surname) -> dict:
    rows = session.execute(
        select(Evidence.verification_status, func.count(Evidence.id))
        .where(Evidence.surname_id == surname.id)
        .group_by(Evidence.verification_status)
    ).all()
    by_status = {status: count for status, count in rows}
    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "verified": by_status.get("verified", 0),
        "disputed": by_status.get("disputed", 0),
        "pending": by_status.get("pending", 0),
        "retracted": by_status.get("retracted", 0),
        "link_stale": by_status.get("link_stale", 0),
    }


def _queried_corpora(session: Session, surname: Surname) -> list[str]:
    rows = session.scalars(
        select(CorpusSearch.corpus_name)
        .where(CorpusSearch.surname_id == surname.id)
        .distinct()
        .order_by(CorpusSearch.corpus_name)
    ).all()
    return list(rows)


def _coverage(session: Session, match: SurnameMatch) -> dict:
    surname = match.surname
    if surname is None:
        return {
            "status": "not_in_corpus",
            "queried_corpora": [],
            "matched_surname": None,
            "match_type": "none",
            "total_evidences": 0,
            "verified_count": 0,
            "disputed_count": 0,
            "pending_count": 0,
            "note": "当前语料中未收录该姓氏：库内既无主记录也无别名匹配。已查询语料为 0 项。",
        }

    counts = _counts(session, surname)
    corpora = _queried_corpora(session, surname)
    if match.match_type in {"alias", "variant"}:
        status = "alias_matched"
    elif counts["total"] > 0:
        status = "in_corpus"
    else:
        status = "not_in_corpus"

    note = None
    if status == "not_in_corpus":
        note = (
            f"当前语料中未收录「{surname.canonical_name}」：库内没有可展示的证据。"
            + (f"已查询语料：{'、'.join(corpora)}。" if corpora else "该姓氏尚无语料审计记录（B-05 未覆盖）。")
        )
    elif status == "alias_matched":
        note = f"输入「{match.matched_input}」通过别名匹配到主记录「{surname.canonical_name}」。"
    elif counts["pending"]:
        note = f"另有 {counts['pending']} 条待核对记录未展示（后端过滤 pending，data-dictionary.md 第 7 节）。"

    return {
        "status": status,
        "queried_corpora": corpora,
        "matched_surname": surname.canonical_name,
        "match_type": match.match_type,
        "total_evidences": counts["total"],
        "verified_count": counts["verified"],
        "disputed_count": counts["disputed"],
        "pending_count": counts["pending"],
        "note": note,
    }


def _source_ref(link) -> dict:
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


def _evidence_summary(evidence: Evidence) -> dict:
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
        "sources": [_source_ref(link) for link in evidence.sources],
    }


def _place_ref(place) -> dict | None:
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


def _pagination(page: int, page_size: int, total: int) -> dict:
    return {"page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total}


def _caveats(counts: dict, stale_link_count: int) -> list[str]:
    """给前端的提示语，前端原样展示、不改写措辞（契约第 4 节）。"""
    messages: list[str] = []
    if counts["disputed"]:
        messages.append(f"该姓氏有 {counts['disputed']} 条存在争议的记录，已并列展示，未做取舍")
    if stale_link_count:
        messages.append(f"有 {stale_link_count} 条记录所引来源链接待复查，书名、卷次与原文已保留")
    if counts["retracted"]:
        messages.append(f"有 {counts['retracted']} 条记录已撤回，可展开查看撤回原因，不作为结论展示")
    if counts["pending"]:
        messages.append(f"有 {counts['pending']} 条待核对记录未对外展示")
    if counts["total"] == 0:
        messages.append(ABSTAIN_TEXT + "：当前语料中没有该姓氏的可展示证据")
    return messages


# ---------------------------------------------------------------- 排序与取数


def _sorted_visible_evidences(session: Session, surname: Surname, evidence_type: str | None = None) -> list[Evidence]:
    """按 SORT_RULE 取可见证据：无年份排最后 → 已核对优先 → year_start 升序。"""
    query = select(Evidence).where(Evidence.surname_id == surname.id, _visible_filter())
    if evidence_type:
        query = query.where(Evidence.evidence_type == evidence_type)
    evidences = list(session.scalars(query))

    def sort_key(item: Evidence) -> tuple:
        # 无年份的记录一律排最后（契约第 5 节），其余按状态优先级 + year_start 升序，末位用编号保证稳定
        return (
            1 if item.year_start is None else 0,
            _status_priority(item.verification_status),
            item.year_start if item.year_start is not None else 0,
            item.evidence_code,
        )

    return sorted(evidences, key=sort_key)


def _earliest_eligible(evidences: list[Evidence]) -> list[Evidence]:
    return [item for item in evidences if item.verification_status != "retracted"]


# ---------------------------------------------------------------- 契约第 4 节


def overview(session: Session, raw_name: str) -> dict:
    """GET /api/surnames/{name}：总览（首屏只调这一个接口）。"""
    match = resolve_surname(session, raw_name)
    coverage = _coverage(session, match)
    surname = match.surname

    if surname is None:
        return {
            "surname": {
                "canonical_name": None,
                "category": None,
                "status": None,
                "description": None,
                "aliases": [],
                "matched_input": match.matched_input,
                "match_type": "none",
            },
            "coverage": coverage,
            "summary": {"earliest": None, "commandery_count": 0, "migration_count": 0, "corpus_check_count": 0},
            "data_quality": {
                "verified_ratio": 0.0,
                "has_disputed": False,
                "stale_link_count": 0,
                "retracted_count": 0,
                "last_reviewed_at": None,
                "caveats": [ABSTAIN_TEXT + "：当前语料中没有该姓氏的可展示证据"],
            },
            "degraded": [],
        }

    counts = _counts(session, surname)
    earliest_candidates = _earliest_eligible(_sorted_visible_evidences(session, surname, "earliest_attestation"))
    commandery_count = session.scalar(
        select(func.count(Evidence.id)).where(
            Evidence.surname_id == surname.id,
            Evidence.evidence_type == "commandery",
            _visible_filter(),
            Evidence.verification_status != "retracted",
        )
    )
    migration_count = session.scalar(
        select(func.count(MigrationEvent.id)).where(MigrationEvent.surname_id == surname.id)
    )
    corpus_check_count = session.scalar(
        select(func.count(CorpusSearch.id)).where(CorpusSearch.surname_id == surname.id)
    )
    last_reviewed = session.scalar(
        select(func.max(Evidence.updated_at)).where(Evidence.surname_id == surname.id, _visible_filter())
    )
    # 链接待复查按“来源版本的 link_status”统计：一条证据挂在失效来源上就计入
    visible_evidences = _sorted_visible_evidences(session, surname)
    stale_link_count = len(
        {
            item.id
            for item in visible_evidences
            if any(link.source_edition.link_status == "stale" for link in item.sources)
        }
    )
    ratio = round(counts["verified"] / counts["total"], 4) if counts["total"] else 0.0

    return {
        "surname": {
            "canonical_name": surname.canonical_name,
            "category": surname.category,
            "status": surname.status,
            "description": surname.description,
            "aliases": [
                {"alias_name": alias.alias_name, "alias_type": alias.alias_type, "note": alias.note}
                for alias in surname.aliases
            ],
            "matched_input": match.matched_input,
            "match_type": match.match_type,
        },
        "coverage": coverage,
        "summary": {
            "earliest": _evidence_summary(earliest_candidates[0]) if earliest_candidates else None,
            "commandery_count": commandery_count or 0,
            "migration_count": migration_count or 0,
            "corpus_check_count": corpus_check_count or 0,
        },
        "data_quality": {
            "verified_ratio": ratio,
            "has_disputed": counts["disputed"] > 0,
            "stale_link_count": stale_link_count,
            "retracted_count": counts["retracted"],
            "last_reviewed_at": to_iso8601(last_reviewed),
            "caveats": _caveats(counts, stale_link_count),
        },
        "degraded": [],
    }


# ---------------------------------------------------------------- 契约第 5 节


def earliest(session: Session, raw_name: str) -> dict:
    """GET /api/surnames/{name}/earliest：最早书证 + 排序依据。

    statement 只描述“当前语料中”能确认的最早，不写绝对结论（契约第 5 节）。
    """
    match = resolve_surname(session, raw_name)
    coverage = _coverage(session, match)
    surname = match.surname
    if surname is None:
        return {
            "surname": match.matched_input,
            "coverage": coverage,
            "items": [],
            "sort_basis": {
                "rule": SORT_RULE,
                "note": SORT_NOTE,
                "candidates_considered": 0,
                "excluded": [],
            },
            "statement": ABSTAIN_TEXT,
            "statement_type": "insufficient_evidence",
        }

    candidates = _sorted_visible_evidences(session, surname, "earliest_attestation")
    eligible = _earliest_eligible(candidates)
    excluded = [
        {"evidence_code": item.evidence_code, "reason": item.verification_status}
        for item in candidates
        if item.verification_status == "retracted"
    ]

    if not eligible:
        statement = ABSTAIN_TEXT
        statement_type = "insufficient_evidence"
    else:
        first = eligible[0]
        when = first.time_label or (
            f"约公元前{-first.year_start}年" if first.year_start is not None and first.year_start < 0
            else f"约公元{first.year_start}年" if first.year_start is not None else "年代不详"
        )
        statement = f"当前语料中可以确认的最早书证为：{first.claim_text}（{first.evidence_code}，{when}）"
        statement_type = "earliest_in_corpus"

    return {
        "surname": match.matched_input,
        "coverage": coverage,
        "items": [_evidence_summary(item) for item in eligible],
        "sort_basis": {
            "rule": SORT_RULE,
            "note": SORT_NOTE,
            "candidates_considered": len(candidates),
            "excluded": excluded,
        },
        "statement": statement,
        "statement_type": statement_type,
    }


# ---------------------------------------------------------------- 契约第 6 节


def commanderies(session: Session, raw_name: str, page: int, page_size: int) -> dict:
    """GET /api/surnames/{name}/commanderies：历史郡望，多个说法并列。

    契约第 6 节的 `name` 在数据字典里没有对应字段（claim_text 是结论而非“名称”），
    当前返回证据结论；若要独立名称字段，需先更新 data-dictionary.md 与契约。
    """
    match = resolve_surname(session, raw_name)
    coverage = _coverage(session, match)
    surname = match.surname
    if surname is None:
        return {
            "surname": match.matched_input,
            "coverage": coverage,
            "items": [],
            "pagination": _pagination(page, page_size, 0),
            "dispute_groups": [],
        }

    all_items = _earliest_eligible(_sorted_visible_evidences(session, surname, "commandery"))
    total = len(all_items)
    start = (page - 1) * page_size
    window = all_items[start : start + page_size]

    items = [
        {
            "commanderies_code": item.evidence_code,
            "name": item.claim_text,
            "period": item.time_label,
            "time_label": item.time_label,
            "year_start": item.year_start,
            "year_end": item.year_end,
            "dispute_group": item.dispute_group,
            "is_disputed": item.verification_status == "disputed",
            "verification_status": item.verification_status,
            "confidence": item.confidence,
            "evidence": _evidence_summary(item),
        }
        for item in window
    ]

    groups: dict[str, list[Evidence]] = {}
    for item in all_items:
        if item.dispute_group:
            groups.setdefault(item.dispute_group, []).append(item)
    dispute_groups = [
        {
            "dispute_group": name,
            "summary": f"同一郡望存在 {len(members)} 种说法，已并列展示，未做取舍",
            "positions": [member.claim_text for member in members],
        }
        for name, members in sorted(groups.items())
    ]

    return {
        "surname": match.matched_input,
        "coverage": coverage,
        "items": items,
        "pagination": _pagination(page, page_size, total),
        "dispute_groups": dispute_groups,
    }


# ---------------------------------------------------------------- 契约第 7 节

MIGRATION_EMPTY_MESSAGE = "当前资料中未找到可核对的迁徙线索"


def migrations(session: Session, raw_name: str, page: int, page_size: int) -> dict:
    """GET /api/surnames/{name}/migrations：迁徙线索（无记录时返回空数组 + 文案）。"""
    match = resolve_surname(session, raw_name)
    coverage = _coverage(session, match)
    surname = match.surname
    if surname is None:
        return {
            "surname": match.matched_input,
            "coverage": coverage,
            "items": [],
            "pagination": _pagination(page, page_size, 0),
            "empty_message": MIGRATION_EMPTY_MESSAGE,
        }

    events = list(session.scalars(select(MigrationEvent).where(MigrationEvent.surname_id == surname.id)))
    events.sort(key=lambda event: (event.year_start is None, event.year_start or 0, event.migration_code))
    total = len(events)
    start = (page - 1) * page_size
    window = events[start : start + page_size]

    items = []
    for event in window:
        items.append(
            {
                "migration_code": event.migration_code,
                "time_label": event.time_label,
                "year_start": event.year_start,
                "year_end": event.year_end,
                "from_place": _place_ref(event.from_place),
                "to_place": _place_ref(event.to_place),
                "event_summary": event.event_summary,
                "relation_status": event.relation_status,
                "confidence": event.confidence,
                "evidences": [
                    {
                        "evidence_code": link.evidence.evidence_code,
                        "relation_type": link.relation_type,
                        "support_type": next(
                            (source.support_type for source in link.evidence.sources if source.support_type), None
                        ),
                    }
                    for link in event.evidence_links
                ],
            }
        )

    return {
        "surname": match.matched_input,
        "coverage": coverage,
        "items": items,
        "pagination": _pagination(page, page_size, total),
        "empty_message": MIGRATION_EMPTY_MESSAGE,
    }


# ---------------------------------------------------------------- 语料审计（D-05 的未收录页面用）


# 该接口尚未写进 docs/api-contract.md，返回形状沿用 Day1 桩实现，未新增字段
def corpus_checks(session: Session, raw_name: str, page: int, page_size: int) -> dict:
    match = resolve_surname(session, raw_name)
    coverage = _coverage(session, match)
    surname = match.surname
    if surname is None:
        return {
            "surname": match.matched_input,
            "coverage": coverage,
            "items": [],
            "pagination": _pagination(page, page_size, 0),
            "summary": {"corpora_checked": [], "total_queries": 0, "total_results": 0},
        }

    records = list(
        session.scalars(
            select(CorpusSearch)
            .where(CorpusSearch.surname_id == surname.id)
            .order_by(CorpusSearch.checked_at.desc(), CorpusSearch.search_code)
        )
    )
    total = len(records)
    start = (page - 1) * page_size
    window = records[start : start + page_size]
    items = [
        {
            "search_code": record.search_code,
            "corpus_name": record.corpus_name,
            "query_text": record.query_text,
            "checked_at": to_iso8601(record.checked_at),
            "result_count": record.result_count,
            "no_result_reason": record.no_result_reason,
            "operator": record.operator,
            "note": record.note,
        }
        for record in window
    ]

    return {
        "surname": match.matched_input,
        "coverage": coverage,
        "items": items,
        "pagination": _pagination(page, page_size, total),
        "summary": {
            "corpora_checked": sorted({record.corpus_name for record in records}),
            "total_queries": total,
            "total_results": sum(record.result_count for record in records),
        },
    }
