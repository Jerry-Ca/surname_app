"""接口层测试（任务 C-11 / C-12 / C-13）：直接调用业务函数，HTTP 层由 scripts/contract_tests.py 覆盖。

运行：python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402

DB_PATH = support.prepare_database()

from app import ask, contract, db, queries, search  # noqa: E402


class OverviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = db.connect(DB_PATH, readonly=True)

    def tearDown(self) -> None:
        self.connection.close()

    def test_four_categories_present_with_evidence_ids(self) -> None:
        payload = queries.overview(self.connection, "李")
        data = payload["data"]
        self.assertEqual(set(payload), {"data", "audit", "message"})
        self.assertEqual(data["surname"]["name"], "李")
        self.assertEqual(data["earliest"]["evidence_id"], "EV-LI-001")
        self.assertEqual([item["evidence_id"] for item in data["commanderies"]], ["EV-LI-002", "EV-LI-003"])
        self.assertEqual(len(data["migrations"]), 1)
        self.assertEqual(len(data["corpus_checks"]), 2)
        self.assertIn("evidence_id", data["earliest"])
        self.assertTrue(data["earliest"]["source"]["url"])

    def test_unknown_surname_is_empty_not_error(self) -> None:
        payload = queries.overview(self.connection, "欧")
        self.assertIsNone(payload["data"]["surname"])
        self.assertEqual(payload["data"]["commanderies"], [])
        self.assertEqual(payload["audit"]["coverage"], "not_in_corpus")
        self.assertTrue(payload["message"])

    def test_sorting_rule_is_verified_first_and_undated_last(self) -> None:
        rows = queries.evidence_rows(self.connection, 1)
        statuses = [row["verification_status"] for row in rows]
        self.assertEqual(statuses[0], "verified")
        self.assertLess(statuses.index("disputed"), statuses.index("retracted"))
        # 排序口径（见 docs/api-contract-v1.md）：已核对优先 → 有来源优先 → 同状态内有年份在前 → 年份升序
        priorities = [queries.STATUS_ORDER[row["verification_status"]] for row in rows]
        self.assertEqual(priorities, sorted(priorities), "状态优先级必须单调（已核对优先）")
        verified = [row for row in rows if row["verification_status"] == "verified"]
        undated = [index for index, row in enumerate(verified) if row["year_start"] is None]
        dated = [index for index, row in enumerate(verified) if row["year_start"] is not None]
        if undated and dated:
            self.assertGreater(min(undated), max(dated), "同一状态内无年份记录排在最后")

    def test_retracted_is_visible_but_not_a_conclusion(self) -> None:
        payload = queries.category(self.connection, "李", "earliest", 1, 20)
        ids = [item["evidence_id"] for item in payload["data"]]
        self.assertNotIn("EV-LI-004", ids, "已撤回记录不得作为最早书证结论")
        candidates = queries.overview(self.connection, "李")["data"]["earliest_candidates"]
        self.assertIn("EV-LI-004", [item["evidence_id"] for item in candidates], "已撤回记录仍可查到")

    def test_disputed_kept_and_flagged(self) -> None:
        payload = queries.category(self.connection, "李", "commanderies", 1, 20)
        self.assertEqual(len(payload["data"]), 2, "同组争议必须全部返回")
        self.assertTrue(all(item["is_disputed"] for item in payload["data"]))
        self.assertEqual(payload["data"][0]["dispute_group"], "DG-LI-01")

    def test_pending_is_hidden_from_lists_but_counted(self) -> None:
        connection = db.connect(DB_PATH)
        try:
            surname_id = db.scalar(connection, "SELECT id FROM surnames WHERE name = '李'")
            connection.execute(
                "INSERT INTO evidences (evidence_id, surname_id, evidence_type, claim_text, original_excerpt,"
                " volume_or_section, source_title, source_url, verification_status, confidence)"
                " VALUES ('EV-LI-900', ?, 'other', '待核对测试结论', '待核对测试原文', '卷九', '测试文献',"
                " 'https://example.org/x', 'pending', 'low')",
                (surname_id,),
            )
            connection.commit()
            payload = queries.overview(self.connection, "李")
            self.assertNotIn("EV-LI-900", json_ids(payload["data"]["commanderies"]))
            self.assertEqual(payload["audit"]["counts"]["pending"], 1)
            self.assertTrue(any("待核对" in (caveat or "") for caveat in [payload["message"]]))
        finally:
            connection.execute("DELETE FROM evidences WHERE evidence_id = 'EV-LI-900'")
            connection.commit()
            connection.close()

    def test_pagination_bounds(self) -> None:
        first = queries.category(self.connection, "李", "commanderies", 1, 1)
        second = queries.category(self.connection, "李", "commanderies", 2, 1)
        self.assertEqual(len(first["data"]), 1)
        self.assertTrue(first["audit"]["pagination"]["has_more"])
        self.assertFalse(second["audit"]["pagination"]["has_more"])


def json_ids(items: list[dict]) -> list[str]:
    return [item["evidence_id"] for item in items]


class SearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = db.connect(DB_PATH, readonly=True)

    def tearDown(self) -> None:
        self.connection.close()

    def test_chinese_substring_hit(self) -> None:
        payload = search.search(self.connection, "原文摘录甲")
        self.assertEqual([item["evidence_id"] for item in payload["data"]], ["EV-LI-001"])
        self.assertEqual(payload["audit"]["retrieval"]["mode"] in {"fts5", "like"}, True)

    def test_wildcards_are_literal(self) -> None:
        payload = search.search(self.connection, "%")
        self.assertEqual(payload["data"], [], "百分号必须按字面量处理，不能变成全表通配")

    def test_blank_query_and_bad_paging_are_422(self) -> None:
        with self.assertRaises(contract.ApiProblem) as blank:
            search.search(self.connection, "   ")
        self.assertEqual(blank.exception.status, 422)
        with self.assertRaises(contract.ApiProblem) as paging:
            search.search(self.connection, "测试", page_size=101)
        self.assertEqual(paging.exception.code, contract.VALIDATION_ERROR)

    def test_scoped_to_surname(self) -> None:
        payload = search.search(self.connection, "契约测试结论甲", raw_surname="欧")
        self.assertEqual(payload["data"], [], "按未收录姓氏检索不应命中别的姓氏的数据")


class AskTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = db.connect(DB_PATH, readonly=True)

    def tearDown(self) -> None:
        self.connection.close()

    def test_without_model_key_returns_unavailable_with_evidence(self) -> None:
        payload = ask.ask(self.connection, question="郡望有哪些说法？", surname="李", top_k=3)
        data = payload["data"]
        self.assertEqual(data["answer_mode"], "unavailable")
        self.assertTrue(data["abstained"])
        self.assertTrue(data["citations"], "降级时仍要返回结构化证据")
        self.assertFalse(data["model"]["used"])

    def test_no_evidence_abstains_with_fixed_text(self) -> None:
        payload = ask.ask(self.connection, question="迁徙路线？", surname="欧")
        self.assertEqual(payload["data"]["answer"], "当前资料不足以确认")
        self.assertEqual(payload["data"]["answer_mode"], "insufficient_evidence")

    def test_unknown_evidence_ids_are_reported(self) -> None:
        payload = ask.ask(self.connection, question="测试", surname="李", evidence_ids=["EV-LI-999"])
        self.assertEqual(payload["data"]["answer_mode"], "insufficient_evidence")
        self.assertIn("EV-LI-999", payload["message"])

    def test_blank_question_is_422(self) -> None:
        with self.assertRaises(contract.ApiProblem):
            ask.ask(self.connection, question="  ")


if __name__ == "__main__":
    unittest.main()
