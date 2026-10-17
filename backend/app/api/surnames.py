"""姓氏查询接口（契约第 4—7 节）。

当前实现状态：返回**契约形状的空结果**，供 D 提前开发加载态与空状态。
真实数据由 C-04 / C-05 接入数据库后替换，字段结构不得改动。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Query

from ..errors import ApiError

router = APIRouter(tags=["surnames"])

SURNAME_PATTERN = re.compile(r"^[\u4e00-\u9fff]{1,8}$")
STUB_NOTE = (
    "后端尚未接入数据库（C-04 未完成）：当前返回契约结构的空结果，"
    "前端可据此开发加载态与空结果；接口字段以 docs/api-contract.md 为准。"
)


def _validate_surname(name: str) -> str:
    candidate = (name or "").strip()
    if not candidate:
        raise ApiError(400, "INVALID_SURNAME_INPUT", "姓氏输入无效：不能为空", {"reason": "empty"})
    if not SURNAME_PATTERN.match(candidate):
        raise ApiError(
            400,
            "INVALID_SURNAME_INPUT",
            "姓氏输入无效：仅支持 1—8 个汉字",
            {"input": name, "reason": "not_chinese_or_too_long"},
        )
    return candidate


def _empty_coverage(name: str, note: str = STUB_NOTE) -> dict:
    return {
        "status": "not_in_corpus",
        "queried_corpora": [],
        "matched_surname": None,
        "match_type": "none",
        "total_evidences": 0,
        "verified_count": 0,
        "disputed_count": 0,
        "pending_count": 0,
        "note": f"{note}（查询词：{name}）",
    }


def _pagination(page: int, page_size: int) -> dict:
    return {"page": page, "page_size": page_size, "total": 0, "has_more": False}


@router.get("/surnames/{name}")
def surname_overview(name: str) -> dict:
    candidate = _validate_surname(name)
    return {
        "surname": {
            "canonical_name": candidate,
            "category": "single",
            "status": "draft",
            "description": None,
            "aliases": [],
            "matched_input": candidate,
            "match_type": "none",
        },
        "coverage": _empty_coverage(candidate),
        "summary": {"earliest": None, "commandery_count": 0, "migration_count": 0, "corpus_check_count": 0},
        "data_quality": {
            "verified_ratio": 0.0,
            "has_disputed": False,
            "stale_link_count": 0,
            "retracted_count": 0,
            "last_reviewed_at": None,
            "caveats": [STUB_NOTE],
        },
        "degraded": [],
    }


@router.get("/surnames/{name}/earliest")
def surname_earliest(name: str) -> dict:
    candidate = _validate_surname(name)
    return {
        "surname": candidate,
        "coverage": _empty_coverage(candidate),
        "items": [],
        "sort_basis": {
            "rule": "verified_first_then_year_start",
            "note": "按已核对优先、year_start 升序；无 year_start 的记录排在最后并单独标注",
            "candidates_considered": 0,
            "excluded": [],
        },
        "statement": "当前资料不足以确认",
        "statement_type": "insufficient_evidence",
    }


@router.get("/surnames/{name}/commanderies")
def surname_commanderies(
    name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    candidate = _validate_surname(name)
    return {
        "surname": candidate,
        "coverage": _empty_coverage(candidate),
        "items": [],
        "pagination": _pagination(page, page_size),
        "dispute_groups": [],
    }


@router.get("/surnames/{name}/migrations")
def surname_migrations(
    name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    candidate = _validate_surname(name)
    return {
        "surname": candidate,
        "coverage": _empty_coverage(candidate),
        "items": [],
        "pagination": _pagination(page, page_size),
        "empty_message": "当前资料中未找到可核对的迁徙线索",
    }


@router.get("/surnames/{name}/corpus-checks")
def surname_corpus_checks(
    name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    candidate = _validate_surname(name)
    return {
        "surname": candidate,
        "coverage": _empty_coverage(candidate),
        "items": [],
        "pagination": _pagination(page, page_size),
        "summary": {"corpora_checked": [], "total_queries": 0, "total_results": 0},
    }
