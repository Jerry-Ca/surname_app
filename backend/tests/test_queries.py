"""查询接口测试（任务 C-04）：契约第 4—7 节 + 语料审计 + 状态可见性。

数据通过 tests/sample_data.py + 导入服务写入临时库，因此这些用例同时验证
“导入 → 查询”整条链路的字段是否对得上契约。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sample_data import build_repo, corpus_row, evidence_row, migration_row, register_row, seed
from sqlalchemy import select

from app.models import Evidence, Surname, SurnameAlias
from app.timeutil import utcnow


@pytest.fixture()
def seeded(tmp_path, fresh_session) -> Path:
    """一份走真实导入流程的数据：来源 1 条、证据 6 条（含争议/撤回/链接待复查/无年份）、迁徙 1 条、语料审计 1 条。"""
    root = build_repo(
        tmp_path / "repo",
        sources=[register_row()],
        evidences=[
            # 已核对的最早书证（有年份）
            evidence_row(evidence_code="EV-LI-001", year_start="-100", year_end="25"),
            # 已核对的郡望，与下一条同属一个争议组
            evidence_row(
                evidence_code="EV-LI-002",
                evidence_type="commandery",
                claim_text="管线测试郡望说法甲（仅用于接口测试）",
                original_excerpt="管线测试原文摘录子（仅用于接口测试）",
                volume_or_section="卷二·测试篇",
                verification_status="disputed",
                dispute_group="DG-LI-01",
                confidence="medium",
                year_start="600",
                year_end="700",
            ),
            evidence_row(
                evidence_code="EV-LI-003",
                evidence_type="commandery",
                claim_text="管线测试郡望说法乙（仅用于接口测试）",
                original_excerpt="管线测试原文摘录丑（仅用于接口测试）",
                volume_or_section="卷三·测试篇",
                verification_status="disputed",
                dispute_group="DG-LI-01",
                confidence="low",
                year_start="620",
                year_end="720",
            ),
            # 链接待复查
            evidence_row(
                evidence_code="EV-LI-004",
                claim_text="管线测试结论戊（仅用于接口测试）",
                original_excerpt="管线测试原文摘录寅（仅用于接口测试）",
                volume_or_section="卷四·测试篇",
                verification_status="link_stale",
                confidence="medium",
                year_start="-200",
            ),
            # 已撤回：必须能查到，但不能作为结论
            evidence_row(
                evidence_code="EV-LI-005",
                claim_text="管线测试已撤回结论庚（仅用于接口测试）",
                original_excerpt="管线测试原文摘录卯（仅用于接口测试）",
                volume_or_section="卷五·测试篇",
                verification_status="retracted",
                confidence="low",
                year_start="-300",
            ),
            # 无年份：排序时排最后
            evidence_row(
                evidence_code="EV-LI-006",
                claim_text="管线测试无年份结论壬（仅用于接口测试）",
                original_excerpt="管线测试原文摘录辰（仅用于接口测试）",
                volume_or_section="卷六·测试篇",
                year_start="",
                year_end="",
                time_label="测试时段表述（年份不详）",
            ),
        ],
        migrations=[migration_row()],
        corpus=[corpus_row()],
    )
    outcomes = seed(root)
    # 样例数据必须真的入库：导入被拒时立刻报出可读错误，而不是让后续断言莫名其妙地失败
    assert outcomes and all(outcome.rejected == 0 for outcome in outcomes), [
        outcome.as_dict() for outcome in outcomes
    ]
    return root


def test_overview_shape_and_counts(client, seeded) -> None:
    response = client.get("/api/surnames/李")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == {"surname", "coverage", "summary", "data_quality", "degraded"}
    surname = body["surname"]
    assert surname["canonical_name"] == "李"
    assert surname["category"] == "single"
    assert surname["status"] == "published"
    assert surname["matched_input"] == "李"
    assert surname["match_type"] == "exact"

    coverage = body["coverage"]
    assert coverage["status"] == "in_corpus"
    assert coverage["matched_surname"] == "李"
    assert coverage["total_evidences"] == 6
    assert coverage["verified_count"] == 2  # EV-LI-001 与 EV-LI-006
    assert coverage["disputed_count"] == 2
    assert coverage["queried_corpora"] == ["测试语料甲"]

    summary = body["summary"]
    assert summary["earliest"]["evidence_code"] == "EV-LI-001"
    assert summary["commandery_count"] == 2
    assert summary["migration_count"] == 1
    assert summary["corpus_check_count"] == 1

    quality = body["data_quality"]
    assert quality["verified_ratio"] == pytest.approx(2 / 6, abs=1e-4)
    assert quality["has_disputed"] is True
    assert quality["retracted_count"] == 1
    assert quality["stale_link_count"] == 0  # 来源版本本身没被标 stale，标的是证据状态
    assert quality["last_reviewed_at"] is not None
    assert any("争议" in caveat for caveat in quality["caveats"])

    assert body["degraded"] == []
    assert response.headers["cache-control"] == "public, max-age=60"


def test_overview_unknown_surname_returns_200_empty_structure(client) -> None:
    """契约第 1.1 节：未收录不是错误。"""
    response = client.get("/api/surnames/欧")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["surname"]["canonical_name"] is None
    assert body["surname"]["match_type"] == "none"
    assert body["coverage"]["status"] == "not_in_corpus"
    assert body["coverage"]["matched_surname"] is None
    assert body["coverage"]["note"], "未收录必须给可读说明，不能是空白页"
    assert body["summary"]["earliest"] is None
    assert body["data_quality"]["caveats"], "必须有提示语给前端原样展示"


def test_earliest_returns_sort_basis_and_statement(client, seeded) -> None:
    body = client.get("/api/surnames/李/earliest").json()

    codes = [item["evidence_code"] for item in body["items"]]
    # 有年份的按已核对优先、年份升序；无年份的最后；已撤回的只出现在 excluded
    assert codes == ["EV-LI-001", "EV-LI-004", "EV-LI-006"]
    assert body["items"][0]["year_start"] == -100
    assert body["items"][-1]["year_start"] is None, "无 year_start 的记录必须排最后并保留 time_label 标注"

    basis = body["sort_basis"]
    assert basis["rule"] == "verified_first_then_year_start"
    assert basis["note"]
    assert basis["candidates_considered"] == 4
    assert basis["excluded"] == [{"evidence_code": "EV-LI-005", "reason": "retracted"}]

    assert body["statement_type"] == "earliest_in_corpus"
    assert "当前语料中可以确认的最早书证" in body["statement"]
    assert "EV-LI-001" in body["statement"]


def test_earliest_without_candidates_abstains(client, fresh_session) -> None:
    """只有郡望证据、没有最早书证时，statement 必须写“当前资料不足以确认”。"""
    fresh_session.add(Surname(canonical_name="陈", category="single", status="draft"))
    fresh_session.commit()

    body = client.get("/api/surnames/陈/earliest").json()
    assert body["items"] == []
    assert body["statement"] == "当前资料不足以确认"
    assert body["statement_type"] == "insufficient_evidence"
    assert body["sort_basis"]["candidates_considered"] == 0


def test_pending_evidence_is_filtered_from_all_endpoints(client, seeded, fresh_session) -> None:
    surname = fresh_session.scalar(select(Surname).where(Surname.canonical_name == "李"))
    fresh_session.add(
        Evidence(
            evidence_code="EV-LI-099",
            surname_id=surname.id,
            evidence_type="earliest_attestation",
            claim_text="管线测试待核对结论（仅用于接口测试）",
            original_excerpt="管线测试待核对原文（仅用于接口测试）",
            volume_or_section="卷九·待核对",
            verification_status="pending",
            confidence="low",
            verified_by="B",
            verification_note="测试用：pending 记录不得对外展示",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    fresh_session.commit()

    overview = client.get("/api/surnames/李").json()
    assert overview["coverage"]["pending_count"] == 1
    assert overview["coverage"]["total_evidences"] == 7  # 统计包含 pending，但列表不含
    assert any("待核对" in caveat for caveat in overview["data_quality"]["caveats"])

    earliest = client.get("/api/surnames/李/earliest").json()
    assert "EV-LI-099" not in [item["evidence_code"] for item in earliest["items"]]
    assert earliest["sort_basis"]["candidates_considered"] == 4

    commanderies = client.get("/api/surnames/李/commanderies").json()
    assert "EV-LI-099" not in [item["commanderies_code"] for item in commanderies["items"]]


def test_retracted_is_visible_but_never_a_conclusion(client, seeded) -> None:
    overview = client.get("/api/surnames/李").json()
    assert overview["data_quality"]["retracted_count"] == 1
    assert any("已撤回" in caveat for caveat in overview["data_quality"]["caveats"])

    earliest = client.get("/api/surnames/李/earliest").json()
    assert all(item["evidence_code"] != "EV-LI-005" for item in earliest["items"])
    assert earliest["sort_basis"]["excluded"][0]["evidence_code"] == "EV-LI-005"


def test_disputed_group_is_returned_in_full(client, seeded) -> None:
    body = client.get("/api/surnames/李/commanderies").json()
    codes = [item["commanderies_code"] for item in body["items"]]
    assert codes == ["EV-LI-002", "EV-LI-003"], "同组说法必须全部返回，不得只留一条"

    item = body["items"][0]
    assert set(item) == {
        "commanderies_code", "name", "period", "time_label", "year_start", "year_end",
        "dispute_group", "is_disputed", "verification_status", "confidence", "evidence",
    }
    assert item["dispute_group"] == "DG-LI-01"
    assert item["is_disputed"] is True
    assert item["evidence"]["evidence_code"] == "EV-LI-002"

    groups = body["dispute_groups"]
    assert len(groups) == 1
    assert groups[0]["dispute_group"] == "DG-LI-01"
    assert len(groups[0]["positions"]) == 2
    assert "并列展示" in groups[0]["summary"]

    assert body["pagination"] == {"page": 1, "page_size": 20, "total": 2, "has_more": False}


def test_commanderies_pagination(client, seeded) -> None:
    first = client.get("/api/surnames/李/commanderies?page=1&page_size=1").json()
    assert len(first["items"]) == 1
    assert first["pagination"] == {"page": 1, "page_size": 1, "total": 2, "has_more": True}

    second = client.get("/api/surnames/李/commanderies?page=2&page_size=1").json()
    assert len(second["items"]) == 1
    assert second["pagination"]["has_more"] is False

    too_large = client.get("/api/surnames/李/commanderies?page_size=101")
    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "VALIDATION_ERROR"


def test_migrations_endpoint_places_and_evidence_links(client, seeded) -> None:
    body = client.get("/api/surnames/李/migrations").json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["migration_code"] == "MG-LI-001"
    assert item["from_place"]["historical_name"] == "测试原地名"
    assert item["from_place"]["location_status"] == "approximate"
    assert item["to_place"]["location_status"] == "unlocatable"
    assert item["to_place"]["coordinates"] is None, "无法定位时坐标必须为 null"
    assert item["relation_status"] == "agreed"
    assert item["evidences"] == [{"evidence_code": "EV-LI-001", "relation_type": None, "support_type": None}]
    assert body["empty_message"] == "当前资料中未找到可核对的迁徙线索"


def test_migrations_empty_result_keeps_message(client, fresh_session) -> None:
    fresh_session.add(Surname(canonical_name="陈", category="single", status="draft"))
    fresh_session.commit()
    body = client.get("/api/surnames/陈/migrations").json()
    assert body["items"] == []
    assert body["pagination"]["total"] == 0
    assert body["empty_message"] == "当前资料中未找到可核对的迁徙线索"


def test_corpus_checks_lists_audit_records(client, seeded) -> None:
    body = client.get("/api/surnames/李/corpus-checks").json()
    assert body["summary"] == {"corpora_checked": ["测试语料甲"], "total_queries": 1, "total_results": 0}
    item = body["items"][0]
    assert item["search_code"] == "CS-LI-001"
    assert item["result_count"] == 0
    assert item["no_result_reason"], "结果数为 0 必须有原因"
    assert item["checked_at"].endswith("Z")


def test_alias_and_compound_matching(client, seeded, fresh_session) -> None:
    surname = fresh_session.scalar(select(Surname).where(Surname.canonical_name == "李"))
    fresh_session.add(SurnameAlias(surname_id=surname.id, alias_name="李氏", alias_type="honorific"))
    fresh_session.add(Surname(canonical_name="欧阳", category="compound", status="draft"))
    fresh_session.commit()

    variant = client.get("/api/surnames/李氏").json()
    assert variant["surname"]["canonical_name"] == "李"
    assert variant["surname"]["match_type"] == "alias"
    assert variant["coverage"]["status"] == "alias_matched"

    compound_body = client.get("/api/surnames/欧阳").json()
    assert compound_body["surname"]["match_type"] == "compound"
    assert compound_body["coverage"]["status"] == "not_in_corpus"


def test_input_normalization_ignores_spaces_and_full_width(client, seeded) -> None:
    """全角与空白由服务层归一化，不要求调用方预处理。"""
    plain = client.get("/api/surnames/李").json()
    spaced = client.get("/api/surnames/%20李%20").json()
    assert spaced["surname"]["canonical_name"] == plain["surname"]["canonical_name"]
    assert spaced["coverage"]["status"] == "in_corpus"


def test_unknown_endpoint_uses_contract_error_shape(client) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "ENDPOINT_NOT_FOUND"
    assert body["error"]["request_id"].startswith("req_")

def test_surname_with_only_pending_evidence_reports_not_in_corpus(client, fresh_session) -> None:
    """只有 pending 记录时不能报 in_corpus：前端会拿到「已收录 + 空列表」的死局（#48）。"""
    from app.models import Evidence

    surname = Surname(canonical_name="陈", category="single", status="draft")
    fresh_session.add(surname)
    fresh_session.commit()
    fresh_session.add(
        Evidence(
            evidence_code="EV-CHEN-001", surname_id=surname.id, evidence_type="other",
            claim_text="仅待核对的探测结论", original_excerpt="仅待核对的探测原文",
            volume_or_section="卷九", verification_status="pending", confidence="low",
            verified_by="B", verification_note="探测：只有 pending",
            created_at=utcnow(), updated_at=utcnow(),
        )
    )
    fresh_session.commit()

    body = client.get("/api/surnames/陈").json()
    coverage = body["coverage"]
    assert coverage["status"] == "not_in_corpus"
    assert coverage["pending_count"] == 1
    assert coverage["total_evidences"] == 1
    assert "人工核验" in coverage["note"] and "不对外展示" in coverage["note"]
    assert any("待核对" in caveat for caveat in body["data_quality"]["caveats"])
    assert body["summary"]["earliest"] is None
