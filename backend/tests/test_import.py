"""导入管线测试（任务 C-03）。

验收项：必填来源、重复证据、非法年份、空原文、外键不存在都要给出**可读错误行**；
支持 dry-run；导入失败整体回滚；每次都写 ingestion_jobs。

样例数据见 tests/sample_data.py（只写临时目录，字段值标注“仅用于接口测试”）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import BACKEND_DIR, REPO_ROOT
from sample_data import (
    CORPUS_HEADER,
    EVIDENCE_HEADER,
    MIGRATION_HEADER,
    REGISTER_HEADER,
    build_repo,
    corpus_row,
    evidence_row,
    migration_row,
    register_row,
    write_csv,
)
from sqlalchemy import func, select

from app.db.session import get_session_factory
from app.errors import ApiError
from app.models import Evidence, IngestionJob, MigrationEvent, Place, SourceEdition, Surname
from app.services import ingestion


@pytest.fixture()
def data_root(tmp_path) -> Path:
    """临时“仓库根”：data/source_register.csv 与 data/verified/ 都在里面。"""
    return build_repo(tmp_path / "repo")


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


def test_uppercase_extension_is_accepted(data_root: Path, fresh_session) -> None:
    """Windows 用户常见的 .CSV 不该被拒；大小写不是安全边界。"""
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(data_root / "data" / "verified" / "Evidences.CSV", EVIDENCE_HEADER, [evidence_row()])
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/Evidences.CSV", session=fresh_session)
    assert (outcome.accepted, outcome.rejected) == (1, 0)


def test_non_csv_under_verified_gets_specific_message(data_root: Path) -> None:
    """verified/ 下的非 CSV 文件：应提示“只接受 .csv”，而不是搬出铁律 2 的通用说明。"""
    (data_root / "data" / "verified" / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ApiError) as error:
        ingestion.resolve_input_ref("data/verified/notes.txt", data_root)
    assert ".csv" in error.value.message
    assert "铁律 2" not in error.value.message


def test_non_utf8_file_is_reported_readably(data_root: Path) -> None:
    """GBK 文件（Excel 默认另存）必须给可读错误，不能抛 UnicodeDecodeError。

    改前实测：经管理接口返回 500 INTERNAL_ERROR，B 看不到“编码问题”提示。
    """
    path = data_root / "data" / "verified" / "evidences.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="gbk", newline="") as handle:
        handle.write("evidence_code,surname\nEV-LI-001,李\n")
    with pytest.raises(ApiError) as error:
        ingestion.read_rows(path)
    assert error.value.status_code == 422
    assert "UTF-8" in error.value.message


def test_admin_import_maps_database_failure_to_503(client, monkeypatch) -> None:
    """数据库不可用时管理接口必须是 503 DATABASE_UNAVAILABLE（契约 1.2 节），不是 500。"""
    from sqlalchemy.exc import OperationalError

    def boom(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(ingestion, "import_file", boom)
    response = client.post(
        "/api/admin/import",
        json={"input_ref": "data/source_register.csv", "operator": "B", "dry_run": True},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


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
    write_csv(data_root / "data" / "verified" / "migrations.csv", MIGRATION_HEADER, [migration_row()])
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    run_import(data_root, "data/verified/evidences.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/migrations.csv", session=fresh_session)
    assert (outcome.accepted, outcome.rejected) == (1, 0)

    event = fresh_session.scalar(select(MigrationEvent).where(MigrationEvent.migration_code == "MG-LI-001"))
    assert event.from_place.historical_name == "测试原地名"
    assert event.to_place.location_status == "unlocatable"
    assert event.to_place.coordinates is None, "无法定位的地点不得有坐标"
    assert [link.evidence.evidence_code for link in event.evidence_links] == ["EV-LI-001"]
    # 事件级有 relation_status；证据级关系类型数据包未标注，保持 null 而不是替 B 猜
    assert event.evidence_links[0].relation_type is None
    assert fresh_session.scalar(select(func.count(Place.id))) == 2


def test_migration_import_rejects_unknown_evidence_code(data_root: Path, fresh_session) -> None:
    write_csv(
        data_root / "data" / "verified" / "migrations.csv",
        MIGRATION_HEADER,
        [migration_row(migration_code="MG-LI-002", evidence_codes="EV-LI-404", confidence="low")],
    )
    outcome = run_import(data_root, "data/verified/migrations.csv", session=fresh_session)
    assert outcome.rejected == 1
    assert outcome.errors[0]["field"] == "evidence_codes"
    assert "不在库中" in outcome.errors[0]["reason"]
    assert fresh_session.scalar(select(func.count(MigrationEvent.id))) == 0


def test_corpus_searches_import(data_root: Path, fresh_session) -> None:
    write_csv(data_root / "data" / "corpus_searches.csv", CORPUS_HEADER, [corpus_row()])
    outcome = run_import(data_root, "data/corpus_searches.csv", session=fresh_session)
    assert (outcome.accepted, outcome.rejected) == (1, 0)

    surname = fresh_session.scalar(select(Surname).where(Surname.canonical_name == "李"))
    assert surname.status == "draft", "只有语料审计时姓氏仍为 draft"


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
    assert set(body) == {
        "job_id", "stage", "total", "accepted", "rejected", "errors", "rolled_back", "started_at", "finished_at"
    }
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
    root = build_repo(tmp_path / "repo", sources=[register_row()])
    write_csv(root / "data" / "raw" / "candidates.csv", EVIDENCE_HEADER, [evidence_row()])

    rejected = subprocess.run(
        [sys.executable, str(script), "--file", str(root / "data" / "raw" / "candidates.csv"), "--operator", "B"],
        capture_output=True, text=True, cwd=BACKEND_DIR,
    )
    assert rejected.returncode != 0
    assert "拒绝导入" in (rejected.stdout + rejected.stderr)

    write_csv(root / "data" / "verified" / "evidences.csv", EVIDENCE_HEADER, [evidence_row()])
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

# ---------------------------------------------------------------- 健壮性探测发现的问题（#48）


def test_overlong_values_are_rejected_readably(data_root: Path, fresh_session) -> None:
    """列长度上限必须在导入侧拦住：SQLite 不强制、PostgreSQL 会拒绝（探测实测）。"""
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(
        data_root / "data" / "verified" / "evidences.csv",
        EVIDENCE_HEADER,
        [evidence_row(surname="李" * 40, work_title="长" * 300)],
    )
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    outcome = run_import(data_root, "data/verified/evidences.csv", session=fresh_session)

    assert outcome.rejected >= 1
    fields = {issue["field"] for issue in outcome.errors}
    assert {"surname", "work_title"} <= fields
    assert any("上限" in issue["reason"] for issue in outcome.errors)
    assert fresh_session.scalar(select(func.count(Evidence.id))) == 0, "超长记录不得入库"
    assert fresh_session.scalar(select(func.count(Surname.id))) == 0


def test_overlong_operator_is_rejected(data_root: Path, fresh_session) -> None:
    """ingestion_jobs.operator 是 String(32)，操作人超长要报文件级错误。"""
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    outcome = run_import(data_root, "data/source_register.csv", dry_run=True, operator="操" * 100, session=fresh_session)
    assert outcome.rejected == 1
    assert outcome.errors[0]["row"] == 0
    assert outcome.errors[0]["field"] == "operator"
    assert "上限" in outcome.errors[0]["reason"]


def test_missing_required_columns_fail_fast(data_root: Path) -> None:
    """缺列要给**一条文件级错误**，而不是每行都报一次（5000 行文件会炸出上万条）。"""
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    header = [column for column in EVIDENCE_HEADER if column != "claim_text"]
    write_csv(data_root / "data" / "verified" / "evidences.csv", header, [evidence_row()])
    outcome = run_import(data_root, "data/verified/evidences.csv")

    assert len(outcome.errors) == 1, f"应当只报一条文件级错误，实际 {len(outcome.errors)} 条"
    assert outcome.errors[0]["row"] == 0
    assert "缺少必需列" in outcome.errors[0]["reason"]
    assert "claim_text" in outcome.errors[0]["reason"]
    # 文件级错误算整份文件被拒：accepted + rejected == total 必须闭环
    assert (outcome.accepted, outcome.rejected) == (0, outcome.total)


def test_duplicate_columns_are_rejected(data_root: Path) -> None:
    """重复列名会让后一列静默覆盖前一列（探测实测），必须拦下。"""
    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    path = data_root / "data" / "verified" / "evidences.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    values = [evidence_row().get(column, "") for column in EVIDENCE_HEADER] + ["第二列"]
    header_line = ",".join(EVIDENCE_HEADER + ["claim_text"])
    value_line = ",".join(f'"{value}"' for value in values)
    path.write_text(f"{header_line}\n{value_line}\n", encoding="utf-8-sig")
    outcome = run_import(data_root, "data/verified/evidences.csv")

    assert len(outcome.errors) == 1
    assert "重复列" in outcome.errors[0]["reason"]


def test_job_id_collision_is_retried(data_root: Path, fresh_session) -> None:
    """并发取号撞车时换下一个号，而不是抛唯一约束异常让整次导入失败。"""
    from app.models import IngestionJob
    from app.timeutil import utcnow

    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    occupied = ingestion.next_job_id(fresh_session)
    fresh_session.add(
        IngestionJob(
            job_id=occupied, source="occupied.csv", stage="load", input_ref="data/x.csv", operator="B",
            dry_run=True, total=0, accepted=0, rejected=0, rolled_back=False, started_at=utcnow(), finished_at=None,
        )
    )
    fresh_session.commit()

    outcome = run_import(data_root, "data/source_register.csv", dry_run=True, session=fresh_session)
    assert outcome.job_id != occupied, "必须换号，不能复用已被占用的 job_id"
    assert outcome.accepted == 1
    stored = set(fresh_session.scalars(select(IngestionJob.job_id)))
    assert {occupied, outcome.job_id} <= stored


def test_every_imported_evidence_has_at_least_one_source(data_root: Path, fresh_session) -> None:
    """契约第 2.2 节要求 sources 至少 1 条：导入路径必须始终建立证据—来源关系。"""
    from app.models import EvidenceSource

    write_csv(data_root / "data" / "source_register.csv", REGISTER_HEADER, [register_row()])
    write_csv(
        data_root / "data" / "verified" / "evidences.csv",
        EVIDENCE_HEADER,
        [evidence_row(), evidence_row(evidence_code="EV-LI-002", volume_or_section="卷二")],
    )
    run_import(data_root, "data/source_register.csv", session=fresh_session)
    run_import(data_root, "data/verified/evidences.csv", session=fresh_session)

    evidences = fresh_session.scalars(select(Evidence)).all()
    assert len(evidences) == 2
    assert all(evidence.sources for evidence in evidences)
    assert fresh_session.scalar(select(func.count(EvidenceSource.id))) == 2
