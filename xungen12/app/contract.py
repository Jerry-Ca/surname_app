"""接口响应封装与序列化（契约 v1 草案，见 docs/api-contract-v1.md）。

所有 /api/* 成功响应都是三个键：`data` / `audit` / `message`（执行清单 §三.7）。
  - data：主体，数组或对象；空结果是 []（不是 null、不是 404）
  - audit：查了什么、命中多少、为什么没查到、分页信息
  - message：给人看的一句话说明（空结果、降级、待核对提示），可为 null
错误响应统一为 {"error": {"code", "message", "details"}}，错误码见契约第 1.2 节。
"""

from __future__ import annotations

import json
from typing import Any

VERSION = "v1"

# 错误码（与 docs/api-contract-v1.md 第 1.2 节一致）
INVALID_INPUT = "INVALID_SURNAME_INPUT"
NOT_FOUND = "ENDPOINT_NOT_FOUND"
VALIDATION_ERROR = "VALIDATION_ERROR"
INTERNAL_ERROR = "INTERNAL_ERROR"
DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"

STATUS_LABELS = {
    "pending": "待核对",
    "verified": "已核对",
    "disputed": "有争议",
    "link_stale": "链接待复查",
    "retracted": "已撤回",
}
TYPE_LABELS = {
    "earliest_attestation": "最早书证",
    "commandery": "郡望",
    "migration": "迁徙",
    "other": "其他",
}


class ApiProblem(Exception):
    """可预期的接口错误：状态码 + 契约错误码 + 给人看的话。不允许用它包住未预期异常。"""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def as_payload(self) -> dict:
        return error(self.code, self.message, self.details)


def ok(data: Any, audit: dict | None = None, message: str | None = None) -> dict:
    return {"data": data, "audit": audit or {}, "message": message}


def error(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def audit_block(
    *,
    coverage: str,
    queried_corpora: list[str] | None = None,
    counts: dict | None = None,
    total_queries: int = 0,
    total_results: int = 0,
    no_result_reason: str | None = None,
    pagination: dict | None = None,
) -> dict:
    block = {
        "coverage": coverage,
        "queried_corpora": queried_corpora or [],
        "total_queries": total_queries,
        "total_results": total_results,
        "no_result_reason": no_result_reason,
        "counts": counts or {},
    }
    if pagination is not None:
        block["pagination"] = pagination
    return block


def pagination(page: int, page_size: int, total: int) -> dict:
    return {"page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total}


def evidence_item(row, *, include_source: bool = True) -> dict:
    """一条证据的对外形状：必须带 evidence_id 与来源字段（执行清单 §三.7）。"""
    item = {
        "evidence_id": row["evidence_id"],
        "evidence_type": row["evidence_type"],
        "evidence_type_label": TYPE_LABELS.get(row["evidence_type"], row["evidence_type"]),
        "claim_text": row["claim_text"],
        "original_excerpt": row["original_excerpt"],
        "volume_or_section": row["volume_or_section"],
        "page_or_location": row["page_or_location"],
        "year_start": row["year_start"],
        "year_end": row["year_end"],
        "time_label": row["time_label"],
        "verification_status": row["verification_status"],
        "verification_status_label": STATUS_LABELS.get(row["verification_status"], row["verification_status"]),
        "confidence": row["confidence"],
        "is_disputed": row["verification_status"] == "disputed",
        "dispute_group": row["dispute_group"],
    }
    if include_source:
        item["source"] = {
            "source_code": row["source_code"],
            "title": row["source_title"],
            "author": row["source_author"],
            "dynasty": row["source_dynasty"],
            "work_type": row["source_work_type"],
            "url": row["source_url"],
            "license_status": row["source_license_status"],
            "accessed_at": row["source_accessed_at"],
        }
    return item


def place_item(row) -> dict | None:
    if row is None:
        return None
    return {
        "historical_name": row["historical_name"],
        "modern_name": row["modern_name"],
        "period": row["period"],
        "location_status": row["location_status"],
        "coordinates": row["coordinates"],
        "location_note": row["location_note"],
    }


def json_dumps(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
