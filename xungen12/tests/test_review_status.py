"""核对结果写库工具测试（任务 C-09 的更新通道）：scripts/apply_review_status.py。

要点：
  - 用**独立临时库**（data/tmp/review-<uuid>/）——这个脚本会改证据状态，
    与 test_api / test_package 共用 support 的库会把它们的断言改坏；
  - 默认预演必须一个字节都不写；--apply 才改状态，且同事务写 review_logs、提交后重建 FTS；
  - 任一行不合规整批回滚（不留半套数据）；重复跑同一个 CSV 幂等。

运行：python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import os
import sqlite3
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402

WORK = support.PROJECT_ROOT / "data" / "tmp" / f"review-{uuid.uuid4().hex[:8]}"
DB_PATH = WORK / "xungen.db"
SCRIPT = support.PROJECT_ROOT / "scripts" / "apply_review_status.py"
HEADER = ["evidence_id", "verification_status", "verified_by", "verification_note"]


def prepare_database() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        return DB_PATH
    env = {**os.environ, "XUNGEN_DB": str(DB_PATH)}
    commands = [
        [support.PYTHON, str(support.PROJECT_ROOT / "scripts" / "init_db.py"), "--db", str(DB_PATH)],
        [support.PYTHON, str(support.PROJECT_ROOT / "scripts" / "import_data.py"), str(support.SAMPLES),
         "--operator", "C", "--apply"],
    ]
    for command in commands:
        completed = subprocess.run(command, cwd=support.PROJECT_ROOT, env=env, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"准备测试库失败：{' '.join(command)}\n{completed.stdout}\n{completed.stderr}")
    return DB_PATH


def write_review_csv(name: str, rows: list[dict]) -> Path:
    path = WORK / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in HEADER})
    return path


def run_tool(csv_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [support.PYTHON, str(SCRIPT), str(csv_path), *args],
        cwd=support.PROJECT_ROOT,
        env={**os.environ, "XUNGEN_DB": str(DB_PATH)},
        capture_output=True,
        text=True,
    )


def status_of(evidence_id: str) -> tuple:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT verification_status, verified_by, verification_note FROM evidences WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()


def log_count() -> int:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT count(*) FROM review_logs").fetchone()[0]


def latest_log(evidence_id: str) -> tuple:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT action, reviewer, before_json, after_json FROM review_logs"
            " WHERE target_id = ? ORDER BY id DESC LIMIT 1",
            (evidence_id,),
        ).fetchone()


def publishable_count() -> int:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT count(*) FROM evidences WHERE verification_status IN"
            " ('verified', 'disputed', 'link_stale', 'retracted')"
        ).fetchone()[0]


def fts_count_or_none() -> int | None:
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as connection:
        exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evidences_fts'"
        ).fetchone()
        if not exists:
            return None
        return connection.execute("SELECT count(*) FROM evidences_fts").fetchone()[0]


class ReviewStatusToolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        prepare_database()

    def test_dry_run_shows_plan_and_writes_nothing(self) -> None:
        before = status_of("EV-LI-003")
        logs_before = log_count()
        csv_path = write_review_csv("dry-run.csv", [
            {"evidence_id": "EV-LI-003", "verification_status": "verified", "verified_by": "C",
             "verification_note": "回看原文：说法与摘录相符"},
        ])
        result = run_tool(csv_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("计划更新 1 条", result.stdout)
        self.assertIn("预演模式", result.stdout)
        self.assertEqual(status_of("EV-LI-003"), before, "预演必须真回滚")
        self.assertEqual(log_count(), logs_before, "预演不得写 review_logs")

    def test_apply_updates_status_writes_log_and_rebuilds_fts(self) -> None:
        logs_before = log_count()
        csv_path = write_review_csv("apply.csv", [
            {"evidence_id": "EV-LI-002", "verification_status": "verified", "verified_by": "C",
             "verification_note": "回看原文后确认（测试）"},
        ])
        result = run_tool(csv_path, "--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("留痕 1 条", result.stdout)
        current_status, verified_by, note = status_of("EV-LI-002")
        self.assertEqual(current_status, "verified")
        self.assertEqual(verified_by, "C")
        self.assertEqual(note, "回看原文后确认（测试）")
        self.assertEqual(log_count(), logs_before + 1)
        action, reviewer, before_json, after_json = latest_log("EV-LI-002")
        self.assertEqual(action, "set_verified")
        self.assertEqual(reviewer, "C")
        self.assertIn('"verification_status": "disputed"', before_json)
        self.assertIn('"verification_status": "verified"', after_json)
        indexed = fts_count_or_none()
        if indexed is not None:
            self.assertEqual(indexed, publishable_count(), "改状态后必须重建全文索引")

    def test_repeat_apply_is_idempotent(self) -> None:
        rows = [{"evidence_id": "EV-LI-002", "verification_status": "verified", "verified_by": "C",
                 "verification_note": "回看原文后确认（测试）"}]
        first = run_tool(write_review_csv("idem-1.csv", rows), "--apply")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        logs_after_first = log_count()
        second = run_tool(write_review_csv("idem-2.csv", rows), "--apply")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("计划更新 0 条", second.stdout, "重复跑同一份核对结果不得刷出第二批留痕")
        self.assertEqual(log_count(), logs_after_first)

    def test_any_bad_row_rolls_back_whole_batch(self) -> None:
        before = status_of("EV-LI-001")
        logs_before = log_count()
        csv_path = write_review_csv("bad-batch.csv", [
            {"evidence_id": "EV-LI-001", "verification_status": "retracted", "verified_by": "C",
             "verification_note": "测试：这一行本身合规"},
            {"evidence_id": "EV-LI-004", "verification_status": "不存在的状态", "verified_by": "C",
             "verification_note": "测试：这一行不合规"},
        ])
        result = run_tool(csv_path, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("整批回滚", result.stderr)
        self.assertEqual(status_of("EV-LI-001"), before, "同批里有坏行时，合规行也不得写入")
        self.assertEqual(log_count(), logs_before)

    def test_publishable_status_requires_verified_by(self) -> None:
        before = status_of("EV-LI-001")
        csv_path = write_review_csv("no-verifier.csv", [
            {"evidence_id": "EV-LI-001", "verification_status": "retracted", "verified_by": "",
             "verification_note": "没写核对人"},
        ])
        result = run_tool(csv_path, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("verified_by", result.stderr)
        self.assertEqual(status_of("EV-LI-001"), before)

    def test_disputed_without_group_is_rejected(self) -> None:
        csv_path = write_review_csv("no-group.csv", [
            {"evidence_id": "EV-LI-005", "verification_status": "disputed", "verified_by": "C",
             "verification_note": "但有争议却没有 dispute_group"},
        ])
        result = run_tool(csv_path, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("dispute_group", result.stderr)
        self.assertEqual(status_of("EV-LI-005")[0], "verified")

    def test_operator_is_recorded_when_verified_by_empty(self) -> None:
        """改回 pending 这类没有署名人场景：review_logs 的 reviewer 用 --operator 兜底。"""
        csv_path = write_review_csv("to-pending.csv", [
            {"evidence_id": "EV-LI-004", "verification_status": "pending", "verified_by": "",
             "verification_note": ""},
        ])
        result = run_tool(csv_path, "--apply", "--operator", "C")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        action, reviewer, _, _ = latest_log("EV-LI-004")
        self.assertEqual(action, "set_pending")
        self.assertEqual(reviewer, "C")


def tearDownModule() -> None:
    # 保留临时库便于排查（与 test_package 一致）；如需彻底清理可删 WORK 目录
    pass


if __name__ == "__main__":
    unittest.main()
