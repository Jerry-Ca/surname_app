"""查询层（任务 C-11）：四类查询 + 姓氏总览 + 语料审计 + 证据排序。

排序规则（执行清单 §三.8，必须可解释、可复现）：
  1. 已核对优先（verified → disputed → link_stale → retracted）
  2. 有来源优先（挂了 source_code 的排前面）
  3. 无年份的记录排最后，其余 year_start 升序
  4. 末位用 evidence_id 收敛，保证分页稳定
  「最早」绝不按插入顺序判断；已撤回（retracted）的记录可以查到，但不作为结论。
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

from . import contract, db

SORT_RULE = "verified_first_then_has_source_then_year_start"
SORT_NOTE = (
    "排序：已核对优先 → 有来源优先 → 无年份记录排最后（year_start 升序）→ 按证据编号收敛；"
    "已撤回记录可查询但不参与「最早」的结论"
)

# 可见性：pending 不外发（数据字典第 7 节）
VISIBLE = ("verified", "disputed", "link_stale", "retracted")
STATUS_ORDER = {"verified": 0, "disputed": 1, "link_stale": 2, "retracted": 3}

_ORDER_BY = """
    CASE e.verification_status
        WHEN 'verified' THEN 0 WHEN 'disputed' THEN 1 WHEN 'link_stale' THEN 2 ELSE 3
    END,
    CASE WHEN e.source_code IS NULL THEN 1 ELSE 0 END,
    CASE WHEN e.year_start IS NULL THEN 1 ELSE 0 END,
    COALESCE(e.year_start, 0),
    e.evidence_id
"""

_EVIDENCE_SELECT = f"""
    SELECT e.*,
           w.author         AS source_author,
           w.dynasty        AS source_dynasty,
           w.work_type      AS source_work_type,
           w.license_status AS source_license_status,
           w.accessed_at    AS source_accessed_at
      FROM evidences e
      LEFT JOIN source_works w ON w.source_code = e.source_code
     WHERE e.verification_status IN ({','.join('?' * len(VISIBLE))})
"""

_NOISE = re.compile(r"[\s　·・.,，。/、\\|()（）\[\]【】\"'“”‘’]+")
_ALIAS_MATCH = {"variant": "variant", "traditional_simplified": "variant", "honorific": "alias", "other": "alias"}


def normalize_input(text: str | None) -> str:
    """查询词标准化：全角转半角、去掉空白与分隔标点（不改字形；繁简靠别名表）。"""
    if not text:
        return ""
    return _NOISE.sub("", unicodedata.normalize("NFKC", text)).strip()


def resolve_surname(connection: sqlite3.Connection, raw: str) -> tuple[sqlite3.Row | None, str, str]:
    """返回 (姓氏行, 匹配方式, 标准化后的输入)。"""
    candidate = normalize_input(raw)
    if not candidate:
        return None, "none", ""
    row = db.query_one(connection, "SELECT * FROM surnames WHERE name = ?", (candidate,))
    if row:
        return row, ("compound" if row["category"] == "compound" else "exact"), candidate
    alias = db.query_one(connection,
        "SELECT a.*, s.* FROM surname_aliases a JOIN surnames s ON s.id = a.surname_id WHERE a.alias_name = ?",
        (candidate,),
    )
    if alias:
        return alias, _ALIAS_MATCH.get(alias["alias_type"], "alias"), candidate
    # 数据侧可能带括号/空白：按首字缩小范围后逐条归一化比对
    if candidate:
        for record in db.query_all(connection,
            "SELECT a.*, s.* FROM surname_aliases a JOIN surnames s ON s.id = a.surname_id WHERE a.alias_name LIKE ?",
            (f"{candidate[0]}%",),
        ):
            if normalize_input(record["alias_name"]) == candidate:
                return record, _ALIAS_MATCH.get(record["alias_type"], "alias"), candidate
    return None, "none", candidate


def counts_for(connection: sqlite3.Connection, surname_id: int) -> dict:
    rows = db.query_all(connection,
        "SELECT verification_status, count(*) AS n FROM evidences WHERE surname_id = ? GROUP BY 1", (surname_id,)
    )
    by_status = {row["verification_status"]: row["n"] for row in rows}
    total = sum(by_status.values())
    return {
        "total": total,
        "verified": by_status.get("verified", 0),
        "disputed": by_status.get("disputed", 0),
        "pending": by_status.get("pending", 0),
        "retracted": by_status.get("retracted", 0),
        "link_stale": by_status.get("link_stale", 0),
        "publishable": sum(by_status.get(key, 0) for key in VISIBLE),
    }


def queried_corpora(connection: sqlite3.Connection, surname_id: int) -> list[str]:
    rows = db.query_all(connection,
        "SELECT DISTINCT corpus_name FROM corpus_searches WHERE surname_id = ? ORDER BY corpus_name", (surname_id,)
    )
    return [row["corpus_name"] for row in rows]


def _corpus_summary(connection: sqlite3.Connection, surname_id: int) -> tuple[int, int, str | None]:
    row = db.query_one(connection,
        "SELECT count(*) AS queries, COALESCE(sum(result_count), 0) AS results FROM corpus_searches WHERE surname_id = ?",
        (surname_id,),
    )
    queries = row["queries"] if row else 0
    results = row["results"] if row else 0
    reason_row = db.query_one(connection,
        "SELECT no_result_reason FROM corpus_searches WHERE surname_id = ? AND result_count = 0 "
        "AND no_result_reason IS NOT NULL LIMIT 1",
        (surname_id,),
    )
    return queries, results, reason_row["no_result_reason"] if reason_row else None


def evidence_rows(
    connection: sqlite3.Connection, surname_id: int, evidence_type: str | None = None
) -> list[sqlite3.Row]:
    sql = _EVIDENCE_SELECT + " AND e.surname_id = ?"
    params: list = list(VISIBLE) + [surname_id]
    if evidence_type:
        sql += " AND e.evidence_type = ?"
        params.append(evidence_type)
    sql += f" ORDER BY {_ORDER_BY}"
    return db.query_all(connection, sql, params)


def _migration_rows(connection: sqlite3.Connection, surname_id: int, page: int, page_size: int) -> tuple[list[dict], int]:
    total = db.scalar(connection, "SELECT count(*) FROM migration_events WHERE surname_id = ?", (surname_id,)) or 0
    rows = db.query_all(connection,
        "SELECT m.*, pf.historical_name AS from_name, pf.modern_name AS from_modern, pf.period AS from_period,"
        "       pf.location_status AS from_status, pf.coordinates AS from_coordinates, pf.location_note AS from_note,"
        "       pt.historical_name AS to_name, pt.modern_name AS to_modern, pt.period AS to_period,"
        "       pt.location_status AS to_status, pt.coordinates AS to_coordinates, pt.location_note AS to_note"
        "  FROM migration_events m"
        "  LEFT JOIN places pf ON pf.id = m.from_place_id"
        "  LEFT JOIN places pt ON pt.id = m.to_place_id"
        " WHERE m.surname_id = ?"
        " ORDER BY CASE WHEN m.year_start IS NULL THEN 1 ELSE 0 END, COALESCE(m.year_start, 0), m.migration_code"
        " LIMIT ? OFFSET ?",
        (surname_id, page_size, (page - 1) * page_size),
    )
    items = []
    for row in rows:
        links = db.query_all(connection,
            "SELECT l.evidence_id, l.relation_type, e.verification_status, e.confidence"
            "  FROM migration_event_evidences l JOIN evidences e ON e.evidence_id = l.evidence_id"
            " WHERE l.migration_event_id = ? ORDER BY l.evidence_id",
            (row["id"],),
        )
        items.append(
            {
                "migration_code": row["migration_code"],
                "time_label": row["time_label"],
                "year_start": row["year_start"],
                "year_end": row["year_end"],
                "event_summary": row["event_summary"],
                "relation_status": row["relation_status"],
                "confidence": row["confidence"],
                "from_place": contract.place_item(
                    {
                        "historical_name": row["from_name"], "modern_name": row["from_modern"],
                        "period": row["from_period"], "location_status": row["from_status"],
                        "coordinates": row["from_coordinates"], "location_note": row["from_note"],
                    }
                    if row["from_name"]
                    else None
                ),
                "to_place": contract.place_item(
                    {
                        "historical_name": row["to_name"], "modern_name": row["to_modern"],
                        "period": row["to_period"], "location_status": row["to_status"],
                        "coordinates": row["to_coordinates"], "location_note": row["to_note"],
                    }
                    if row["to_name"]
                    else None
                ),
                "evidences": [
                    {
                        "evidence_id": link["evidence_id"],
                        "relation_type": link["relation_type"],
                        "verification_status": link["verification_status"],
                        "confidence": link["confidence"],
                    }
                    for link in links
                ],
            }
        )
    return items, total


def _corpus_rows(connection: sqlite3.Connection, surname_id: int, page: int, page_size: int) -> tuple[list[dict], int]:
    total = db.scalar(connection, "SELECT count(*) FROM corpus_searches WHERE surname_id = ?", (surname_id,)) or 0
    rows = db.query_all(connection,
        "SELECT * FROM corpus_searches WHERE surname_id = ?"
        " ORDER BY checked_at DESC, search_code LIMIT ? OFFSET ?",
        (surname_id, page_size, (page - 1) * page_size),
    )
    items = [
        {
            "search_code": row["search_code"],
            "corpus_name": row["corpus_name"],
            "query_text": row["query_text"],
            "checked_at": row["checked_at"],
            "result_count": row["result_count"],
            "no_result_reason": row["no_result_reason"],
            "operator": row["operator"],
            "note": row["note"],
        }
        for row in rows
    ]
    return items, total


def _coverage_and_message(
    connection: sqlite3.Connection, surname_row: sqlite3.Row | None, match_type: str, raw_input: str
) -> tuple[str, dict, list[str], str | None, int, int, str | None]:
    """返回 (coverage, 计数, 已查语料, 说明, 查询次数, 结果数, 未命中原因)。"""
    if surname_row is None:
        return (
            "not_in_corpus", {}, [], f"当前语料中未收录「{normalize_input(raw_input)}」：库内既无主记录也无别名匹配。",
            0, 0, None,
        )
    counts = counts_for(connection, surname_row["id"])
    corpora = queried_corpora(connection, surname_row["id"])
    queries, results, reason = _corpus_summary(connection, surname_row["id"])
    if match_type in {"alias", "variant"}:
        coverage = "alias_matched"
        message = f"输入「{raw_input}」通过别名匹配到主记录「{surname_row['name']}」。"
    elif counts["publishable"] > 0:
        coverage = "in_corpus"
        message = None
        if counts["pending"]:
            message = f"另有 {counts['pending']} 条待核对记录未对外展示（后端过滤 pending）。"
    else:
        coverage = "not_in_corpus"
        if counts["pending"]:
            message = (
                f"已查到 {counts['pending']} 条「{surname_row['name']}」的记录，但都没有通过人工核验，按规则不对外展示。"
            )
        elif corpora:
            message = f"当前语料中未收录「{surname_row['name']}」：已查询 {'、'.join(corpora)}，均无可展示证据。"
        else:
            message = f"当前语料中未收录「{surname_row['name']}」：该姓氏尚无语料审计记录。"
    return coverage, counts, corpora, message, queries, results, reason


def overview(connection: sqlite3.Connection, raw_name: str) -> dict:
    """GET /api/surnames/{name}：一次给出四类数据（执行清单 §七 的最小验收）。"""
    surname_row, match_type, normalized = resolve_surname(connection, raw_name)
    coverage, counts, corpora, message, queries, results, reason = _coverage_and_message(
        connection, surname_row, match_type, raw_name
    )
    audit = contract.audit_block(
        coverage=coverage, queried_corpora=corpora, counts=counts,
        total_queries=queries, total_results=results, no_result_reason=reason,
    )

    if surname_row is None:
        return contract.ok(
            {"surname": None, "matched_input": normalized, "match_type": "none", "earliest": None,
             "commanderies": [], "migrations": [], "corpus_checks": []},
            audit, message,
        )

    earliest_rows = [row for row in evidence_rows(connection, surname_row["id"], "earliest_attestation")]
    eligible = [row for row in earliest_rows if row["verification_status"] != "retracted"]
    # 「最早」不能靠插入顺序：优先取有年份的记录；全部无年份时退回第一条并在 message 里说明
    dated = [row for row in eligible if row["year_start"] is not None]
    conclusion = (dated or eligible)[0] if eligible else None
    if conclusion is not None and conclusion["year_start"] is None:
        message = (message + " " if message else "") + "当前可供判断的最早书证没有明确年份，只能按来源表述（time_label）展示。"
    commanderies = evidence_rows(connection, surname_row["id"], "commandery")
    migrations, _ = _migration_rows(connection, surname_row["id"], 1, 100)
    corpus_checks, _ = _corpus_rows(connection, surname_row["id"], 1, 100)

    data = {
        "surname": {
            "name": surname_row["name"],
            "category": surname_row["category"],
            "pinyin": surname_row["pinyin"],
            "status": surname_row["status"],
            "description": surname_row["description"],
            "matched_input": normalized,
            "match_type": match_type,
            "aliases": [
                {"alias_name": alias["alias_name"], "alias_type": alias["alias_type"], "note": alias["note"]}
                for alias in db.query_all(connection,
                    "SELECT * FROM surname_aliases WHERE surname_id = ? ORDER BY alias_name", (surname_row["id"],)
                )
            ],
        },
        "earliest": contract.evidence_item(conclusion) if conclusion else None,
        "earliest_candidates": [contract.evidence_item(row) for row in earliest_rows],
        "commanderies": [contract.evidence_item(row) for row in commanderies],
        "migrations": migrations,
        "corpus_checks": corpus_checks,
    }
    return contract.ok(data, audit, message)


def category(connection: sqlite3.Connection, raw_name: str, kind: str, page: int, page_size: int) -> dict:
    """GET /api/surnames/{name}/{kind}：单独取一类（列表 + 分页）。"""
    surname_row, match_type, _ = resolve_surname(connection, raw_name)
    coverage, counts, corpora, message, queries, results, reason = _coverage_and_message(
        connection, surname_row, match_type, raw_name
    )
    if surname_row is None:
        audit = contract.audit_block(
            coverage=coverage, queried_corpora=corpora, counts=counts, total_queries=queries,
            total_results=results, no_result_reason=reason, pagination=contract.pagination(page, page_size, 0),
        )
        return contract.ok([], audit, message)

    if kind == "migrations":
        items, total = _migration_rows(connection, surname_row["id"], page, page_size)
    elif kind == "corpus-checks":
        items, total = _corpus_rows(connection, surname_row["id"], page, page_size)
    else:  # earliest / commanderies
        evidence_type = {"earliest": "earliest_attestation", "commanderies": "commandery"}[kind]
        rows = evidence_rows(connection, surname_row["id"], evidence_type)
        if kind == "earliest":
            rows = [row for row in rows if row["verification_status"] != "retracted"]
        total = len(rows)
        window = rows[(page - 1) * page_size : page * page_size]
        items = [contract.evidence_item(row) for row in window]

    if not items and message is None:
        message = _empty_message(kind, surname_row["name"])
    audit = contract.audit_block(
        coverage=coverage, queried_corpora=corpora, counts=counts, total_queries=queries,
        total_results=results, no_result_reason=reason, pagination=contract.pagination(page, page_size, total),
    )
    if kind == "earliest":
        audit["sort_rule"] = SORT_RULE
        audit["sort_note"] = SORT_NOTE
    return contract.ok(items, audit, message)


def _empty_message(kind: str, name: str) -> str:
    return {
        "earliest": f"当前语料中未找到「{name}」的最早书证，当前资料不足以确认。",
        "commanderies": f"当前资料中未找到「{name}」的郡望记载。",
        "migrations": f"当前资料中未找到「{name}」的迁徙线索。",
        "corpus-checks": f"「{name}」还没有语料审计记录。",
    }[kind]
