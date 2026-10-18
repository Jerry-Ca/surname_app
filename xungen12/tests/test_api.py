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

from app import ask, contract, db, fts, queries, search  # noqa: E402


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

    def test_origins_container_exposes_other_evidence(self) -> None:
        """得姓源流/氏族世系（evidence_type=other）必须有容器（裁决 2026-10-18），元素与郡望同形。"""
        data = queries.overview(self.connection, "李")["data"]
        self.assertEqual([item["evidence_id"] for item in data["origins"]], ["EV-LI-005"])
        self.assertEqual(set(data["origins"][0]), set(data["commanderies"][0]))

    def test_unknown_surname_shell_keeps_all_evidence_blocks(self) -> None:
        data = queries.overview(self.connection, "欧")["data"]
        for key in ("earliest", "earliest_candidates", "commanderies", "origins", "migrations", "corpus_checks"):
            self.assertIn(key, data, f"空壳响应缺 {key}（前端直接 .map() 会炸）")
        self.assertIsNone(data["earliest"])
        self.assertEqual(data["origins"], [])
        self.assertEqual(data["earliest_candidates"], [])


class CoverageTest(unittest.TestCase):
    """coverage 四档（裁决 2026-10-18）：queried_unverified 不得再和 not_in_corpus 混为一谈。"""

    NAMES = ("唐", "曹", "谭")

    def setUp(self) -> None:
        self.writer = db.connect(DB_PATH)
        self.connection = db.connect(DB_PATH, readonly=True)

    def tearDown(self) -> None:
        for name in self.NAMES:
            for (surname_id,) in self.writer.execute("SELECT id FROM surnames WHERE name = ?", (name,)).fetchall():
                self.writer.execute("DELETE FROM evidences WHERE surname_id = ?", (surname_id,))
                self.writer.execute("DELETE FROM corpus_searches WHERE surname_id = ?", (surname_id,))
                self.writer.execute("DELETE FROM surnames WHERE id = ?", (surname_id,))
        self.writer.commit()
        self.writer.close()
        self.connection.close()

    def add_surname(self, name: str) -> int:
        self.writer.execute("INSERT INTO surnames (name, category) VALUES (?, 'single')", (name,))
        self.writer.commit()
        return db.scalar(self.writer, "SELECT id FROM surnames WHERE name = ?", (name,))

    def test_only_pending_is_queried_unverified_not_not_in_corpus(self) -> None:
        surname_id = self.add_surname("唐")
        self.writer.execute(
            "INSERT INTO evidences (evidence_id, surname_id, evidence_type, claim_text, original_excerpt,"
            " volume_or_section, source_title, source_url, verification_status, confidence)"
            " VALUES ('EV-TANG-900', ?, 'other', '待核对测试结论', '待核对测试原文', '卷一', '测试文献',"
            " 'https://example.org/t', 'pending', 'low')",
            (surname_id,),
        )
        self.writer.commit()
        payload = queries.overview(self.connection, "唐")
        self.assertEqual(payload["audit"]["coverage"], "queried_unverified")
        self.assertEqual(payload["audit"]["counts"]["pending"], 1)
        self.assertNotIn("未收录", payload["message"] or "", "有 pending 记录时不得说「未收录」")
        self.assertIn("人工核验", payload["message"])
        self.assertEqual(payload["data"]["origins"], [], "pending 不出现在任何 data 列表里")

    def test_corpus_clue_without_records_is_queried_unverified(self) -> None:
        surname_id = self.add_surname("曹")
        self.writer.execute(
            "INSERT INTO corpus_searches (search_code, surname_id, corpus_name, query_text, checked_at,"
            " result_count, operator) VALUES ('CS-CAO-900', ?, '测试语料', '曹', '2026-10-18T00:00:00Z', 3, 'C')",
            (surname_id,),
        )
        self.writer.commit()
        payload = queries.overview(self.connection, "曹")
        self.assertEqual(payload["audit"]["coverage"], "queried_unverified")
        self.assertIn("1 部报有相关记载线索", payload["message"] or "")

    def test_corpus_checked_without_clue_stays_not_in_corpus(self) -> None:
        surname_id = self.add_surname("谭")
        self.writer.execute(
            "INSERT INTO corpus_searches (search_code, surname_id, corpus_name, query_text, checked_at,"
            " result_count, no_result_reason, operator)"
            " VALUES ('CS-TAN-900', ?, '测试语料', '谭', '2026-10-18T00:00:00Z', 0,"
            " '该部语料中未见可归入本姓的记载', 'C')",
            (surname_id,),
        )
        self.writer.commit()
        payload = queries.overview(self.connection, "谭")
        self.assertEqual(payload["audit"]["coverage"], "not_in_corpus")
        self.assertIn("未收录", payload["message"] or "")


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

    def test_short_query_falls_back_to_like(self) -> None:
        """不足三字的词在 trigram 索引里没有 token，必须回落 LIKE 子串，否则一律 0 命中。"""
        payload = search.search(self.connection, "测试")
        self.assertTrue(payload["data"], "两字查询必须能命中")
        self.assertIn("EV-LI-001", json_ids(payload["data"]))
        if fts.available(self.connection):
            self.assertEqual(payload["audit"]["retrieval"]["mode"], "like")
            self.assertIn("不足三字", payload["audit"]["retrieval"]["note"] or "")

    def test_three_char_query_still_uses_index(self) -> None:
        payload = search.search(self.connection, "原文摘录")
        self.assertTrue(payload["data"])
        self.assertEqual(
            payload["audit"]["retrieval"]["mode"],
            "fts5" if fts.available(self.connection) else "like",
            "三字及以上的查询不该被短查询回落影响",
        )

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
