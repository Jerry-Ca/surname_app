"""搜索服务测试（任务 C-05）：标准化、匹配、全文检索、排序、分页与降级。

检索能力是「精确匹配 → 全文检索」的主干（架构第 6 节），因此这里既测正常路径，
也测 pg_trgm 不可用时的 LIKE 回落（CI 里永远是回落路径：本机与 CI 都用 SQLite）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sample_data import build_repo, evidence_row, register_row, seed
from sqlalchemy import select

from app.errors import ApiError
from app.models import Evidence, Surname
from app.services import search
from app.timeutil import utcnow


@pytest.fixture()
def corpus(tmp_path, fresh_session) -> Path:
    """两条姓氏：李（4 条证据 + 1 条 pending）与王（1 条证据），用来验证范围与过滤。"""
    root = build_repo(
        tmp_path / "repo",
        sources=[register_row()],
        evidences=[
            evidence_row(
                evidence_code="EV-LI-001",
                claim_text="管线测试结论甲（仅用于接口测试，不代表历史事实）",
                original_excerpt="管线测试原文摘录丙（仅用于接口测试）",
                year_start="-100",
                year_end="25",
            ),
            evidence_row(
                evidence_code="EV-LI-002",
                claim_text="管线测试结论乙：含检索词甲丙（仅用于接口测试）",
                original_excerpt="管线测试原文摘录丁（仅用于接口测试）",
                volume_or_section="卷二·测试篇",
                verification_status="disputed",
                dispute_group="DG-LI-01",
                confidence="medium",
                year_start="600",
                year_end="700",
            ),
            evidence_row(
                evidence_code="EV-LI-003",
                claim_text="管线测试结论戊（仅用于接口测试）",
                original_excerpt="管线测试原文摘录含检索词甲丙（仅用于接口测试）",
                volume_or_section="卷三·检索词甲丙",
                verification_status="link_stale",
                confidence="low",
                year_start="",
                year_end="",
                time_label="测试时段表述（年份不详）",
            ),
            evidence_row(
                evidence_code="EV-WANG-001",
                surname="王",
                claim_text="管线测试结论己：另一个姓氏也含检索词甲丙（仅用于接口测试）",
                original_excerpt="管线测试原文摘录庚（仅用于接口测试）",
                volume_or_section="卷一·测试篇",
            ),
        ],
    )
    outcomes = seed(root)
    assert outcomes and all(outcome.rejected == 0 for outcome in outcomes), [
        outcome.as_dict() for outcome in outcomes
    ]
    return root


def _surname(session, name: str) -> Surname:
    return session.scalar(select(Surname).where(Surname.canonical_name == name))


# ---------------------------------------------------------------- 标准化与匹配


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("　李 ", "李"),
        ("李·氏", "李氏"),
        ("欧 阳", "欧阳"),
        ("ＡＢ", "AB"),
        ("（李）", "李"),
        ("", ""),
        (None, ""),
        ("  ·  ", ""),
    ],
)
def test_normalize_input(raw, expected) -> None:
    assert search.normalize_input(raw) == expected


def test_resolve_surname_exact_compound_alias_variant(corpus, fresh_session) -> None:
    from app.models import SurnameAlias

    exact = search.resolve_surname(fresh_session, " 李 ")
    assert exact.surname.canonical_name == "李"
    assert exact.match_type == "exact"

    fresh_session.add(Surname(canonical_name="欧阳", category="compound", status="draft"))
    fresh_session.add(SurnameAlias(surname_id=_surname(fresh_session, "李").id, alias_name="李氏", alias_type="honorific"))
    fresh_session.add(
        SurnameAlias(
            surname_id=_surname(fresh_session, "李").id,
            alias_name="李（繁体测试）",
            alias_type="traditional_simplified",
        )
    )
    fresh_session.commit()

    compound = search.resolve_surname(fresh_session, "欧阳")
    assert compound.match_type == "compound"

    honorific = search.resolve_surname(fresh_session, "李氏")
    assert honorific.match_type == "alias"
    assert honorific.alias_type == "honorific"
    assert honorific.surname.canonical_name == "李"

    variant = search.resolve_surname(fresh_session, "李（繁体测试）")
    assert variant.match_type == "variant"

    unknown = search.resolve_surname(fresh_session, "欧")
    assert unknown.surname is None
    assert unknown.match_type == "none"


# ---------------------------------------------------------------- 全文检索


def test_search_matches_claim_excerpt_and_volume(corpus, fresh_session) -> None:
    page = search.search_evidences(fresh_session, "检索词甲丙")
    by_code = {hit.evidence_code: hit for hit in page.items}
    assert set(by_code) == {"EV-LI-002", "EV-LI-003", "EV-WANG-001"}
    assert by_code["EV-LI-002"].matched_field == "claim_text"
    assert by_code["EV-LI-003"].matched_field == "original_excerpt"  # 摘录先命中，卷次也含该词
    assert page.total == 3


def test_search_snippet_is_a_real_substring(corpus, fresh_session) -> None:
    hit = search.search_evidences(fresh_session, "摘录含检索词甲丙").items[0]
    assert hit.snippet and "检索词甲丙" in hit.snippet
    assert hit.snippet.replace("…", "") in hit.evidence.original_excerpt, "片段必须是原文子串，不允许生成"


def test_search_can_be_scoped_to_one_surname(corpus, fresh_session) -> None:
    surname = _surname(fresh_session, "李")
    page = search.search_evidences(fresh_session, "检索词甲丙", surname=surname)
    assert {hit.evidence_code for hit in page.items} == {"EV-LI-002", "EV-LI-003"}
    assert page.total == 2


def test_search_ranks_verified_first_then_by_field(corpus, fresh_session) -> None:
    page = search.search_evidences(fresh_session, "检索词甲丙")
    statuses = [hit.evidence.verification_status for hit in page.items]
    # 已核对优先：EV-LI-002 是 disputed，EV-LI-003 是 link_stale，EV-WANG-001 是 verified
    assert statuses[0] == "verified"
    assert statuses[-1] == "link_stale"
    # 同为命中，结论命中排在摘录命中之前
    fields = [hit.matched_field for hit in page.items]
    assert fields.index("claim_text") < fields.index("original_excerpt")


def test_pending_evidence_is_not_searchable(corpus, fresh_session) -> None:
    surname = _surname(fresh_session, "李")
    fresh_session.add(
        Evidence(
            evidence_code="EV-LI-099",
            surname_id=surname.id,
            evidence_type="other",
            claim_text="待核对记录也写了检索词甲丙（仅用于接口测试）",
            original_excerpt="待核对原文（仅用于接口测试）",
            volume_or_section="卷九·待核对",
            verification_status="pending",
            confidence="low",
            verified_by="B",
            verification_note="测试用：pending 不参与检索",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    fresh_session.commit()

    page = search.search_evidences(fresh_session, "检索词甲丙")
    assert "EV-LI-099" not in {hit.evidence_code for hit in page.items}


# ---------------------------------------------------------------- 分页与错误


def test_search_pagination_is_stable_and_has_no_gaps(corpus, fresh_session) -> None:
    first = search.search_evidences(fresh_session, "检索词甲丙", page=1, page_size=2)
    second = search.search_evidences(fresh_session, "检索词甲丙", page=2, page_size=2)

    assert first.total == second.total == 3
    assert first.has_more is True
    assert second.has_more is False
    codes = [hit.evidence_code for hit in first.items] + [hit.evidence_code for hit in second.items]
    assert sorted(codes) == ["EV-LI-002", "EV-LI-003", "EV-WANG-001"], "分页之间不重复、不丢项"


@pytest.mark.parametrize(("page", "page_size"), [(0, 20), (1, 0), (1, 101)])
def test_search_rejects_invalid_pagination(corpus, fresh_session, page, page_size) -> None:
    with pytest.raises(ApiError) as error:
        search.search_evidences(fresh_session, "检索词甲丙", page=page, page_size=page_size)
    assert error.value.status_code == 422
    assert error.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize("blank", ["", "   ", "·、。"])
def test_search_rejects_blank_query(corpus, fresh_session, blank: str) -> None:
    with pytest.raises(ApiError) as error:
        search.search_evidences(fresh_session, blank)
    assert error.value.status_code == 422
    assert error.value.code == "VALIDATION_ERROR"


def test_search_returns_empty_page_when_nothing_matches(corpus, fresh_session) -> None:
    page = search.search_evidences(fresh_session, "语料中不存在的检索词")
    assert page.items == []
    assert page.total == 0
    assert page.has_more is False


# ---------------------------------------------------------------- 降级与稳定 JSON


def test_like_fallback_is_reported_on_non_postgresql(corpus, fresh_session) -> None:
    """CI 与本地都是 SQLite：必须走 LIKE 基线，并把降级信息暴露出来。"""
    assert search.supports_trigram(fresh_session) is False
    page = search.search_evidences(fresh_session, "检索词甲丙")
    assert "fulltext_like_fallback" in page.degraded
    assert search.dialect_name(fresh_session) == "sqlite"


def test_search_json_shape_is_stable_and_contract_shaped(corpus, fresh_session) -> None:
    payload = search.search_evidences(fresh_session, "检索词甲丙", page=1, page_size=2).as_dict()

    assert set(payload) == {"query", "items", "pagination", "degraded"}
    assert payload["query"] == "检索词甲丙"
    assert set(payload["pagination"]) == {"page", "page_size", "total", "has_more"}
    assert payload["pagination"] == {"page": 1, "page_size": 2, "total": 3, "has_more": True}

    item = payload["items"][0]
    assert set(item) == {
        "evidence_code", "evidence_type", "claim_text", "original_excerpt", "volume_or_section",
        "year_start", "year_end", "time_label", "verification_status", "confidence", "sources",
    }
    assert "id" not in item, "数据库自增 id 不对外暴露"
    assert item["sources"], "命中必须带来源信息"
    assert {"source_code", "work_title", "volume_or_section", "link_status", "support_type"} <= set(item["sources"][0])


def test_search_hit_keeps_evidence_id_for_downstream_retrieval(corpus, fresh_session) -> None:
    """E-01 的向量检索需要按同一条记录对齐，因此内部保留 evidence.id。"""
    hit = search.search_evidences(fresh_session, "检索词甲丙").items[0]
    assert isinstance(hit.evidence_id, int)
    assert hit.evidence_code.startswith("EV-")
