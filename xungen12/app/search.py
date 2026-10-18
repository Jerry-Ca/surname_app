r"""全文检索（任务 C-12）：FTS5（trigram）优先，不可用回落 LIKE 基线。

为什么用 trigram 而不是默认分词：SQLite 的 unicode61 分词器会把一整段连续汉字当成**一个词**，
「陇西」在「陇西郡望」里根本匹配不到。trigram 按三字滑窗建索引，中文子串检索才有效；
旧版 SQLite 没有 trigram 时不建索引，直接走 LIKE（结果一样正确，只是慢）。
检索词与数据里的 % _ \ 都按字面量处理，不允许一个 % 变成全表通配。
"""

from __future__ import annotations

import sqlite3

from . import contract, db, fts
from .queries import (
    _EVIDENCE_SELECT,
    _ORDER_BY,
    VISIBLE,
    _coverage_and_message,
    normalize_input,
    resolve_surname,
)

MAX_PAGE_SIZE = 100
SNIPPET_RADIUS = 24
_FIELD_PRIORITY = {"claim_text": 0, "original_excerpt": 1, "volume_or_section": 2}


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _fts_query(text: str) -> str:
    """把检索词变成 FTS5 的短语查询（双引号包裹并转义内部引号）。"""
    return '"' + text.replace('"', '""') + '"'


def retrieval_mode(connection: sqlite3.Connection) -> tuple[str, str | None]:
    """返回 (模式, 说明)。模式是 fts5 或 like。"""
    if fts.available(connection):
        return "fts5", None
    return "like", "本机 SQLite 没有可用的 FTS5 索引，已回落 LIKE 检索（结果一致，数据量大时会慢一些）"


def _matched_field(row: sqlite3.Row, needle: str) -> str:
    for field_name in ("claim_text", "original_excerpt", "volume_or_section"):
        value = row[field_name] or ""
        if needle in value:
            return field_name
    return "claim_text"


def _snippet(text: str, needle: str) -> str | None:
    position = text.find(needle)
    if position < 0:
        return None
    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(text), position + len(needle) + SNIPPET_RADIUS)
    return f"{'…' if start > 0 else ''}{text[start:end]}{'…' if end < len(text) else ''}"


def _validate_page(page: int, page_size: int) -> None:
    if page < 1:
        raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "page 必须 >= 1", {"field": "page", "value": page})
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise contract.ApiProblem(
            422, contract.VALIDATION_ERROR, f"page_size 必须在 1—{MAX_PAGE_SIZE} 之间",
            {"field": "page_size", "value": page_size},
        )


def search(
    connection: sqlite3.Connection,
    query: str,
    *,
    raw_surname: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """在结论 / 原文摘录 / 卷次里检索证据，返回契约信封（data/audit/message）。"""
    _validate_page(page, page_size)
    needle = normalize_input(query)
    if not needle:
        raise contract.ApiProblem(
            422, contract.VALIDATION_ERROR, "查询词不能为空（去掉空白与标点后为空）", {"field": "q"}
        )

    surname_row, match_type, normalized_name = resolve_surname(connection, raw_surname or "") if raw_surname else (None, "", "")
    coverage, counts, corpora, message, queries, results, reason = _coverage_and_message(
        connection, surname_row, match_type, raw_surname or ""
    )

    mode, mode_note = retrieval_mode(connection)
    # trigram 分词器的每个 token 是连续三个字符：不足三字的查询在索引里没有对应 token，
    # 既不报错也不命中（「郡望」「邓氏」「南阳」这类两字词恰恰是最常用的查询）。
    # 短查询直接走下面的 LIKE 分支（结果一致，只是慢一点），三字及以上继续用索引。
    if mode == "fts5" and len(needle) < 3:
        mode, mode_note = "like", "查询不足三字，trigram 索引无法匹配，已改用 LIKE 子串检索"
    where = ""
    params: list = list(_VISIBLE_PARAMS)
    if mode == "fts5":
        where = (
            " AND e.evidence_id IN (SELECT evidence_id FROM evidences_fts WHERE evidences_fts MATCH ?)"
        )
        params.append(_fts_query(needle))
    else:
        pattern = _like_pattern(needle)
        where = (
            " AND (e.claim_text LIKE ? ESCAPE '\\' OR e.original_excerpt LIKE ? ESCAPE '\\'"
            " OR e.volume_or_section LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])
    if raw_surname and surname_row is None:
        # 指定了姓氏但库里既无主记录也无别名：返回空结果 + 说明，
        # 绝不退化成全库检索（否则在「欧」的页面上会冒出「李」的证据）
        audit = contract.audit_block(
            coverage=coverage, queried_corpora=corpora, counts=counts, total_queries=queries,
            total_results=results, no_result_reason=reason,
            pagination=contract.pagination(page, page_size, 0),
        )
        audit["retrieval"] = {"mode": mode, "query": needle, "note": mode_note}
        return contract.ok([], audit, message or f"当前语料中未收录「{normalized_name}」，没有可检索的证据。")

    if surname_row is not None:
        where += " AND e.surname_id = ?"
        params.append(surname_row["id"])

    try:
        total = db.scalar(connection, f"SELECT count(*) FROM evidences e WHERE 1=1{_visibility_clause()}{where}", params) or 0
        rows = db.query_all(
            connection,
            f"{_EVIDENCE_SELECT}{where} ORDER BY {_ORDER_BY} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
    except sqlite3.OperationalError as exc:  # FTS 索引损坏或语法不被接受：立刻回落 LIKE，不让检索失败
        if mode != "fts5":
            raise
        mode, mode_note = "like", f"FTS5 查询失败（{str(exc)[:60]}），已回落 LIKE 检索"
        pattern = _like_pattern(needle)
        fallback_where = (
            " AND (e.claim_text LIKE ? ESCAPE '\\' OR e.original_excerpt LIKE ? ESCAPE '\\'"
            " OR e.volume_or_section LIKE ? ESCAPE '\\')"
        )
        fallback_params: list = [*_VISIBLE_PARAMS, pattern, pattern, pattern]
        if surname_row is not None:
            fallback_where += " AND e.surname_id = ?"
            fallback_params.append(surname_row["id"])
        total = db.scalar(
            connection, f"SELECT count(*) FROM evidences e WHERE 1=1{_visibility_clause()}{fallback_where}",
            fallback_params,
        ) or 0
        rows = db.query_all(
            connection,
            f"{_EVIDENCE_SELECT}{fallback_where} ORDER BY {_ORDER_BY} LIMIT ? OFFSET ?",
            [*fallback_params, page_size, (page - 1) * page_size],
        )

    items = []
    for row in rows:
        item = contract.evidence_item(row)
        matched = _matched_field(row, needle)
        item["matched_field"] = matched
        item["snippet"] = _snippet(row["original_excerpt"] or "", needle) or _snippet(row["claim_text"] or "", needle)
        items.append(item)

    audit = contract.audit_block(
        coverage=coverage, queried_corpora=corpora, counts=counts, total_queries=queries,
        total_results=results, no_result_reason=reason,
        pagination=contract.pagination(page, page_size, total),
    )
    audit["retrieval"] = {"mode": mode, "query": needle, "note": mode_note}
    if not items:
        message = message or f"没有检索到与「{needle}」相关的证据（已检索结论、原文摘录与卷次）。"
    return contract.ok(items, audit, message)


_VISIBLE_PARAMS = tuple(VISIBLE)


def _visibility_clause() -> str:
    return f" AND e.verification_status IN ({','.join('?' * len(VISIBLE))})"
