"""导入管线测试（任务 C-03）。

验收项：必填来源、重复证据、非法年份、空原文、外键不存在都要给出**可读错误行**；
支持 dry-run；导入失败整体回滚；每次都写 ingestion_jobs。

注意：下面的 CSV 内容只存在于临时目录，用来验证管线，不是任何真实历史数据
（AGENTS.md 铁律 1：不得编造书名、卷次、原文）。测试库用真实迁移建表（见 conftest）。
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import BACKEND_DIR, REPO_ROOT
from sqlalchemy import func, select

from app.db.session import get_session_factory
from app.errors import ApiError
from app.models import Evidence, IngestionJob, MigrationEvent, Place, SourceEdition, Surname
from app.services import ingestion

REGISTER_HEADER = [
    "source_code", "work_title", "work_author", "dynasty", "work_type", "edition",
    "publisher", "source_provider", "source_url", "license_status", "accessed_at",
    "content_hash", "notes",
]
EVIDENCE_HEADER = [
    "evidence_code", "surname", "evidence_type", "claim_text", "work_title", "work_author",
    "dynasty", "volume_or_section", "page_or_location", "original_excerpt", "source_code",
    "source_url", "access_note", "accessed_at", "verification_status", "confidence",
    "verified_by", "verification_note", "dispute_group", "year_start", "year_end", "time_label",
]
MIGRATION_HEADER = [
    "migration_code", "surname", "time_label", "year_start", "year_end", "from_historical_name",
    "from_modern_name", "from_location_status", "to_historical_name", "to_modern_name",
    "to_location_status", "event_summary", "relation_status", "confidence", "evidence_codes",
    "verified_by", "verification_note",
]


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig：与 data-pipeline.md 第 3 节一致（Windows 上 Excel 打开不乱码）
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})
    return path


def register_row() -> dict[str, str]:
    return {
        "source_code": "SRC-001",
        "work_title": "管线测试文献乙",
        "work_author": "测试编写者",
        "dynasty": "测试朝代",
        "work_type": "classic",
        "source_provider": "测试平台",
        "source_url": "https://example.org/item/1",
        "license_status": "public_domain",
        "accessed_at": "2026-10-17T03:21:00Z",
    }


def evidence_row(**overrides: str) -> dict[str, str]:
    row = {
        "evidence_code": "EV-LI-001",
        "surname": "李",
        "evidence_type": "earliest_attestation",
        "claim_text": "管线测试结论甲（仅用于接口测试，不代表历史事实）",
        "work_title": "管线测试文献乙",
        "work_author": "测试编写者",
        "volume_or_section": "卷一·测试篇",
        "page_or_location": "第 10 页",
        "original_excerpt": "管线测试原文摘录丙（仅用于接口测试）",
        "source_code": "SRC-001",
        "source_url": "https://example.org/item/1",
        "accessed_at": "2026-10-17T03:21:00Z",
        "verification_status": "verified",
        "confidence": "high",
        "verified_by": "B",
        "verification_note": "测试用核验说明：核对字段是否完整",
        "year_start": "-100",
        "year_end": "25",
        "time_label": "测试时间段表述",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def data_root(tmp_path) -> Path:
    """临时“仓库根”：data/source_register.csv 与 data/verified/ 都在里面。"""
    root = tmp_path / "repo"
    (root / "data" / "verified").mkdir(parents=True)
    (root / "data" / "raw").mkdir(parents=True)
    return root


@pytest.fixture()
def fresh_session():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def run_import(data_root: Path, ref: str, *, dry_run: bool = False, operator: str = "B", session=None):
    own = session is None
    session = session or get_session_factory()()
    try:
        return ingestion.import_file(
            session, input_ref=ref, operator=operator, stage="load", dry_run=dry_run, root=data_root
        )
    finally:
        if own:
            session.close()


# ---------------------------------------------------------------- 路径策略


def test_only_verified_and_registered_files_can_be_imported(data_root: Path) -> None:
    write_csv(data_root / "data" / "raw" / "candidates.csv", EVIDENCE_HEADER, [])
    with pytest.raises(ApiError) as error:
        ingestion.resolve_input_ref("data/raw/candidates.csv", data_root)
    assert error.value.status_code == 422
    assert "data/verified" in error.value.message

    with pytest.raises(ApiError):
        ingestion.resolve_input_ref("C:/Windows/system32/anything.csv", data_root)
    with pytest.raises(ApiError):
        ingestion.resolve_input_ref("../outside.csv", data_root)


def test_missing_file_is_reported_readably(data_root: Path) -> None:
    with pytest.raises(ApiError) as error:
        ingestion.resolve_input_ref("data/verified/evidences.csv", data_root)
    assert "文件不存在" in error.value.message


# ---------------------------------------------------------------- 正常路径


def test_dry_run_validates_without_writing(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(data_root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, [evidence_row()])
    run_import(data_root, "data/source_register.csv", session=fresh_session)

    outcome = run_import(data_root, "data/verified/evidences.csv", dry_run=True, session=fresh_session)
    assert outcome.total == 1
    assert outcome.accepted == 1
    assert outcome.rejected == 0
    assert outcome.rolled_back is False
    assert fresh_session.scalar(select(func.count(Evidence.id))) == 0, "dry-run 不允许写库"

    # dry-run 也要留审计记录，B 交付时用它说明“校验过几次、什么时候验的”
    job = fresh_session.scalar(select(IngestionJob).order_by(IngestionJob.id.desc()))
    assert job.dry_run is True
    assert job.accepted == 1
    assert job.operator == "B"
    assert job.stage == "load"
    assert job.job_id.startswith("JOB-")


def test_apply_writes_evidence_with_source_and_surname(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(data_root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, [evidence_row()])
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/evidences.csv", session=fresh_session)

    assert (outcome.accepted, outcome.rejected, outcome.rolled_back) == (1, 0, False)

    evidence = fresh_session.scalar(select(Evidence).where(Evidence.evidence_code == "EV-LI-001"))
    assert evidence.verification_status == "verified"
    assert evidence.year_start == -100 and evidence.year_end == 25
    assert [source.source_edition.source_code for source in evidence.sources] == ["SRC-001"]

    surname = fresh_session.scalar(select(Surname).where(Surname.canonical_name == "李"))
    assert surname.category == "single"
    assert surname.status == "published", "有可展示证据的姓氏应为 published"

    edition = fresh_session.scalar(select(SourceEdition).where(SourceEdition.source_code == "SRC-001"))
    assert edition.license_status == "public_domain"
    assert edition.link_status == "ok"


def test_compound_surname_is_marked_compound(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(
        data_root / "data" / "verified" / "evidences.csv",
        EVIDENCE_HEADER,
        [evidence_row(evidence_code="EV-OUYANG-001", surname="欧阳")],
    )
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    run_import(data_root, "data/verified/evidences.csv", session=fresh_session)

    surname = fresh_session.scalar(select(Surname).where(Surname.canonical_name == "欧阳"))
    assert surname.category == "compound"


def test_migration_import_links_evidence_and_places(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(data_root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, [evidence_row()])
    write_csv(
        data_root / "data" / "verified" / "migrations.csv",
        MIGRATION_HEADER,
        [
            {
                "migration_code": "MG-LI-001",
                "surname": "李",
                "time_label": "测试时间段表述",
                "year_start": "600",
                "year_end": "700",
                "from_historical_name": "测试原地名",
                "from_modern_name": "测试今地名甲",
                "from_location_status": "approximate",
                "to_historical_name": "测试迁入地名",
                "to_modern_name": "测试今地名乙",
                "to_location_status": "unlocatable",
                "event_summary": "管线测试迁徙概述（仅用于接口测试）",
                "relation_status": "agreed",
                "confidence": "medium",
                "evidence_codes": "EV-LI-001",
                "verified_by": "B",
                "verification_note": "测试用核验说明：确认证据编号可解析",
            }
        ],
    )
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    run_import(data_root, "data/verified/evidences.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/migrations.csv", session=fresh_session)
    assert (outcome.accepted, outcome.rejected) == (1, 0)

    event = fresh_session.scalar(select(MigrationEvent).where(MigrationEvent.migration_code == "MG-LI-001"))
    assert event.from_place.historical_name == "测试原地名"
    assert event.to_place.location_status == "unlocatable"
    assert event.to_place.coordinates is None, "无法定位的地点不得有坐标"
    assert [link.evidence.evidence_code for link in event.evidence_links] == ["EV-LI-001"]
    # 事件级有 relation_status，证据级关系类型数据包未标注，保持 null 而不是替 B 猜
    assert event.evidence_links[0].relation_type is None
    assert fresh_session.scalar(select(func.count(Place.id))) == 2


def test_migration_import_rejects_unknown_evidence_code(data_root: Path, fresh_session) -> None:
    write_csv(
        data_root / "data" / "verified" / "migrations.csv",
        MIGRATION_HEADER,
        [
            {
                "migration_code": "MG-LI-002",
                "surname": "李",
                "time_label": "测试时间段表述",
                "from_historical_name": "测试原地名",
                "from_location_status": "approximate",
                "to_historical_name": "测试迁入地名",
                "to_location_status": "approximate",
                "event_summary": "管线测试迁徙概述（仅用于接口测试）",
                "relation_status": "agreed",
                "confidence": "low",
                "evidence_codes": "EV-LI-404",
                "verified_by": "B",
                "verification_note": "测试用核验说明",
            }
        ],
    )
    outcome = run_import(data_root, "data/verified/migrations.csv", session=fresh_session)
    assert outcome.rejected == 1
    assert outcome.errors[0]["field"] == "evidence_codes"
    assert "不在库中" in outcome.errors[0]["reason"]
    assert fresh_session.scalar(select(func.count(MigrationEvent.id))) == 0


# ---------------------------------------------------------------- 错误路径


def test_errors_are_readable_and_nothing_is_written(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(
        data_root / "data" / "verified" / "evidences.csv",
        EVIDENCE_HEADER,
        [
            evidence_row(),
            evidence_row(evidence_code="EV-LI-002", original_excerpt="", year_start="唐初"),
            evidence_row(evidence_code="EV-LI-003", source_code="SRC-404"),
            evidence_row(evidence_code="EV-LI-004", volume_or_section="见原文"),
            evidence_row(evidence_code="EV-LI-005", verification_status="pending"),
        ],
    )
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/evidences.csv", session=fresh_session)

    assert outcome.total == 5
    assert outcome.rejected == 4
    assert outcome.rolled_back is True, "有错误即整体不写入"

    by_field = {(issue["row"], issue["field"]): issue["reason"] for issue in outcome.errors}
    assert any(field == "original_excerpt" for _, field in by_field)
    assert any("整数年" in reason for reason in by_field.values())
    assert any(field == "source_code" and "不存在" in reason for (_, field), reason in by_field.items())
    assert any(field == "volume_or_section" for _, field in by_field)
    assert any("铁律 2" in reason or "data/raw" in reason for reason in by_field.values())
    assert all(issue["row"] >= 2 for issue in outcome.errors), "错误必须带真实行号"

    assert fresh_session.scalar(select(func.count(Evidence.id))) == 0
    job = fresh_session.scalar(select(IngestionJob).order_by(IngestionJob.id.desc()))
    assert job.rejected == 4
    assert job.rolled_back is True
    assert job.error_log and job.error_log[0]["reason"]


def test_placeholder_text_is_rejected(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(
        data_root / "data" / "verified" / "evidences.csv",
        EVIDENCE_HEADER,
        [evidence_row(claim_text="<一句话事实结论，须与原文一致>")],
    )
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/evidences.csv", session=fresh_session)
    assert outcome.rejected == 1
    assert "占位符" in outcome.errors[0]["reason"]


def test_duplicate_evidence_code_is_rejected_on_reimport(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(data_root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, [evidence_row()])
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    run_import(data_root, "data/verified/evidences.csv", session=fresh_session)

    outcome = run_import(data_root, "data/verified/evidences.csv", session=fresh_session)
    assert outcome.rejected == 1
    assert "已入库" in outcome.errors[0]["reason"]
    assert fresh_session.scalar(select(func.count(Evidence.id))) == 1


def test_disputed_requires_dispute_group(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(
        data_root / "data" / "verified" / "evidences.csv",
        EVIDENCE_HEADER,
        [evidence_row(verification_status="disputed", dispute_group="")],
    )
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/evidences.csv", session=fresh_session)
    assert outcome.rejected == 1
    assert outcome.errors[0]["field"] == "dispute_group"


# ---------------------------------------------------------------- 通过管理接口（端到端）


def test_admin_import_endpoint_writes_data(data_root: Path, client, monkeypatch, fresh_session) -> None:
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(data_root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, [evidence_row()])
    # 数据目录指向临时根，避免往仓库的 data/ 写测试数据（data/ 是 B 的目录）
    monkeypatch.setattr(ingestion, "REPO_ROOT", data_root)

    headers = {"X-Admin-Token": "test-admin-token"}
    register_response = client.post(
        "/api/admin/import",
        json={"input_ref": "data/source_register.csv", "operator": "B", "stage": "load", "dry_run": False},
        headers=headers,
    )
    assert register_response.status_code == 200, register_response.text

    response = client.post(
        "/api/admin/import",
        json={"input_ref": "data/verified/evidences.csv", "operator": "B", "stage": "load", "dry_run": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"job_id", "stage", "total", "accepted", "rejected", "errors", "rolled_back", "started_at", "finished_at"}
    assert body["accepted"] == 1 and body["rejected"] == 0
    assert body["job_id"].startswith("JOB-")

    fresh_session.expire_all()
    assert fresh_session.scalar(select(func.count(Evidence.id))) == 1
    assert fresh_session.scalar(select(func.count(IngestionJob.id))) == 2


def test_admin_import_rejects_out_of_scope_path_with_422(client, monkeypatch, data_root: Path) -> None:
    write_csv(data_root / "data" / "raw" / "candidates.csv", EVIDENCE_HEADER, [evidence_row()])
    monkeypatch.setattr(ingestion, "REPO_ROOT", data_root)
    response = client.post(
        "/api/admin/import",
        json={"input_ref": "data/raw/candidates.csv", "operator": "B", "dry_run": True},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 脚本入口（B 交付时用）


def test_import_script_rejects_raw_and_accepts_verified(tmp_path: Path) -> None:
    """脚本是 B 的验收入口，位置策略必须与后端一致。"""
    script = REPO_ROOT / "scripts" / "import_data.py"
    root = tmp_path / "repo"
    (root / "data" / "raw").mkdir(parents=True)
    (root / "data" / "verified").mkdir(parents=True)
    write_csv(root / "data" / "raw" / "candidates.csv", EVIDENCE_HEADER, [evidence_row()])

    rejected = subprocess.run(
        [sys.executable, str(script), "--file", str(root / "data" / "raw" / "candidates.csv"), "--operator", "B"],
        capture_output=True, text=True, cwd=BACKEND_DIR,
    )
    assert rejected.returncode != 0
    assert "拒绝导入" in (rejected.stdout + rejected.stderr)

    write_csv(root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, [evidence_row()])
    write_csv(root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    accepted = subprocess.run(
        [
            sys.executable, str(script),
            "--file", str(root / "data" / "verified" / "evidences.csv"),
            "--operator", "B", "--data-root", str(root / "data"),
        ],
        capture_output=True, text=True, cwd=BACKEND_DIR,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "本地校验通过" in accepted.stdout
    assert "干跑模式" in accepted.stdout
