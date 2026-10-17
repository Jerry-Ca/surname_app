"""数据包校验与导入测试（任务 C-09）：坏数据必须被指到行、整体不写入。

运行：python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402

DB_PATH = support.prepare_database()

from app import db, validation  # noqa: E402

EVIDENCE_HEADER = [
    "evidence_id", "surname", "evidence_type", "claim_text", "original_excerpt", "volume_or_section",
    "source_title", "source_author", "source_url", "verification_status", "confidence", "verified_by",
    "verification_note", "dispute_group", "year_start", "year_end", "time_label",
]


def write_rows(path: Path, header: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})
    return path


def evidence_row(**over) -> dict:
    row = {
        "evidence_id": "EV-XX-001", "surname": "李", "evidence_type": "other", "claim_text": "测试结论",
        "original_excerpt": "测试原文", "volume_or_section": "卷一", "source_title": "测试文献",
        "source_author": "测试作者", "source_url": "https://example.org/x", "verification_status": "verified",
        "confidence": "high", "verified_by": "B", "verification_note": "测试用核验说明",
    }
    row.update(over)
    return row


class ValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = support.WORK_ROOT / f"case-{self._testMethodName}"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def test_empty_excerpt_is_rejected_with_line_and_fix(self) -> None:
        path = write_rows(self.tmp / "evidences.csv", EVIDENCE_HEADER, [evidence_row(original_excerpt="   ")])
        report = validation.validate_package(path)
        self.assertFalse(report.ok())
        issue = report.issues[0]
        self.assertEqual(issue.row, 2)
        self.assertEqual(issue.field, "original_excerpt")
        self.assertTrue(issue.fix, "错误必须带修复建议")

    def test_illegal_status_and_year_order_are_rejected(self) -> None:
        path = write_rows(self.tmp / "evidences.csv", EVIDENCE_HEADER, [
            evidence_row(verification_status="bogus"),
            evidence_row(evidence_id="EV-XX-002", year_start="100", year_end="-100"),
        ])
        report = validation.validate_package(path)
        fields = {issue.field for issue in report.issues}
        self.assertIn("verification_status", fields)
        self.assertIn("year_start", fields)

    def test_disputed_without_group_and_bad_url(self) -> None:
        path = write_rows(self.tmp / "evidences.csv", EVIDENCE_HEADER, [
            evidence_row(verification_status="disputed", source_url="ftp://example.org/x"),
        ])
        report = validation.validate_package(path)
        fields = {issue.field for issue in report.issues}
        self.assertIn("dispute_group", fields)
        self.assertIn("source_url", fields)

    def test_duplicate_evidence_id_in_file(self) -> None:
        path = write_rows(self.tmp / "evidences.csv", EVIDENCE_HEADER, [evidence_row(), evidence_row()])
        report = validation.validate_package(path)
        self.assertTrue(any("编号重复" in issue.reason for issue in report.issues))

    def test_missing_required_column_reports_once(self) -> None:
        header = [column for column in EVIDENCE_HEADER if column != "claim_text"]
        path = write_rows(self.tmp / "evidences.csv", header, [evidence_row()])
        report = validation.validate_package(path)
        self.assertEqual(len(report.issues), 1)
        self.assertIn("缺少必需列", report.issues[0].reason)

    def test_gbk_file_gives_readable_encoding_error(self) -> None:
        path = self.tmp / "evidences.csv"
        path.write_bytes("evidence_id,surname\nEV-XX-001,李\n".encode("gbk"))
        report = validation.validate_package(path)
        self.assertTrue(any("UTF-8" in issue.reason for issue in report.issues))

    def test_pending_row_needs_no_verifier_but_publishable_does(self) -> None:
        pending = write_rows(self.tmp / "pending.csv", EVIDENCE_HEADER, [
            evidence_row(verification_status="pending", verified_by="", verification_note="")
        ])
        publishable = write_rows(self.tmp / "verified.csv", EVIDENCE_HEADER, [
            evidence_row(verified_by="", verification_note="")
        ])
        self.assertTrue(validation.validate_package(pending).ok())
        self.assertFalse(validation.validate_package(publishable).ok())


class ImportTest(unittest.TestCase):
    def test_samples_imported_once_and_duplicate_rejected(self) -> None:
        connection = db.connect(DB_PATH, readonly=True)
        try:
            self.assertEqual(db.scalar(connection, "SELECT count(*) FROM evidences"), 5)
        finally:
            connection.close()
        result = support.run_script("import_data.py", str(support.SAMPLES), "--operator", "C", "--apply")
        self.assertEqual(result.returncode, 1, "重复导入必须被拒")
        self.assertIn("已入库", result.stdout)

    def test_failed_import_writes_nothing(self) -> None:
        tmp = support.WORK_ROOT / "bad-package"
        write_rows(tmp / "evidences.csv", EVIDENCE_HEADER, [
            evidence_row(evidence_id="EV-XX-101", surname="契约新姓", original_excerpt="")
        ])
        result = support.run_script("import_data.py", str(tmp), "--operator", "C", "--apply")
        self.assertEqual(result.returncode, 1)
        connection = db.connect(DB_PATH, readonly=True)
        try:
            self.assertEqual(
                db.scalar(connection, "SELECT count(*) FROM evidences WHERE evidence_id = 'EV-XX-101'"), 0,
                "校验失败时不得写入任何记录",
            )
            self.assertIsNotNone(
                db.scalar(connection, "SELECT job_id FROM ingestion_jobs ORDER BY id DESC LIMIT 1"),
                "每次导入都要留 ingestion_jobs 记录",
            )
        finally:
            connection.close()

    def test_json_package_imports_and_directory_mode_picks_up_json(self) -> None:
        """执行清单 §三.5 要求「支持 CSV/JSON」：单文件 JSON 与目录含 JSON 都要能导。"""
        import json
        import os
        import subprocess
        import sys

        pkg = support.WORK_ROOT / "json-package"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "source_register.json").write_text(
            json.dumps([{
                "source_code": "SRC-900", "title": "JSON 测试文献", "author": "测试作者",
                "work_type": "classic", "source_provider": "测试平台",
                "source_url": "https://example.org/j", "license_status": "public_domain",
                "accessed_at": "2026-10-17T00:00:00Z",
            }], ensure_ascii=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(support.PROJECT_ROOT / "scripts" / "import_data.py"),
             str(pkg / "source_register.json"), "--operator", "C", "--apply"],
            cwd=support.PROJECT_ROOT, env={**os.environ}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("通过 1", result.stdout)

        # 再跑一次目录模式（会看到同一个 JSON）→ 重复导入必须被拒并整体回滚
        again = subprocess.run(
            [sys.executable, str(support.PROJECT_ROOT / "scripts" / "import_data.py"),
             str(pkg), "--operator", "C", "--apply"],
            cwd=support.PROJECT_ROOT, env={**os.environ}, capture_output=True, text=True,
        )
        self.assertEqual(again.returncode, 1)
        self.assertIn("已整体回滚", again.stdout)

    def test_constraints_are_enforced_by_sqlite(self) -> None:
        connection = db.connect(DB_PATH)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO evidences (evidence_id, surname_id, evidence_type, claim_text, original_excerpt,"
                    " volume_or_section, source_title, source_url, verification_status, confidence)"
                    " VALUES ('EV-BAD-001', 999, 'other', 'x', '  ', '卷一', '书', 'https://e.org', 'verified', 'high')"
                )
        finally:
            connection.rollback()
            connection.close()


def tearDownModule() -> None:
    # 保留临时库便于排查；如需彻底清理可删除 support.WORK_ROOT
    pass


if __name__ == "__main__":
    unittest.main()
