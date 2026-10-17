"""契约形状测试：即使数据未接入，响应结构也必须与 docs/api-contract.md 一致。

这些断言是前后端联调的基础——D 在 C 完成数据库接入前就能依赖它们开发。
"""

from __future__ import annotations

import pytest

SURNAME = "李"


@pytest.mark.parametrize(
    ("path", "required_keys"),
    [
        (f"/api/surnames/{SURNAME}", {"surname", "coverage", "summary", "data_quality", "degraded"}),
        (f"/api/surnames/{SURNAME}/earliest", {"surname", "coverage", "items", "sort_basis", "statement", "statement_type"}),
        (f"/api/surnames/{SURNAME}/commanderies", {"surname", "coverage", "items", "pagination", "dispute_groups"}),
        (f"/api/surnames/{SURNAME}/migrations", {"surname", "coverage", "items", "pagination", "empty_message"}),
        (f"/api/surnames/{SURNAME}/corpus-checks", {"surname", "coverage", "items", "pagination", "summary"}),
    ],
)
def test_query_endpoints_match_contract(client, path: str, required_keys: set[str]) -> None:
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert required_keys <= set(response.json())


def test_coverage_structure(client) -> None:
    coverage = client.get(f"/api/surnames/{SURNAME}").json()["coverage"]
    assert set(coverage) >= {
        "status", "queried_corpora", "matched_surname", "match_type",
        "total_evidences", "verified_count", "disputed_count", "pending_count", "note",
    }
    assert coverage["status"] in {"in_corpus", "not_in_corpus", "alias_matched"}


@pytest.mark.parametrize("bad_input", ["", "123", "李" * 9, "%20"])
def test_invalid_surname_input_returns_400(client, bad_input: str) -> None:
    response = client.get(f"/api/surnames/{bad_input or ' '}")
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] in {"INVALID_SURNAME_INPUT", "VALIDATION_ERROR"}


def test_ask_degrades_without_model(client) -> None:
    response = client.post("/api/ask", json={"surname": "李", "question": "郡望有哪些记载？"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer_mode"] == "degraded_no_model"
    assert body["abstained"] is True
    assert body["answer"] == "当前资料不足以确认"
    assert set(body) >= {"answer", "answer_mode", "abstained", "abstain_reason", "citations", "retrieved_count", "model", "notice"}


def test_admin_requires_token(client) -> None:
    response = client.post("/api/admin/import", json={"input_ref": "data/verified/evidences.csv", "operator": "B"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_UNAUTHORIZED"


def test_admin_with_token_is_not_implemented_yet(client) -> None:
    response = client.post(
        "/api/admin/import",
        json={"input_ref": "data/verified/evidences.csv", "operator": "B"},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"
