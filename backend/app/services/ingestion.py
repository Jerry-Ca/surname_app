"""数据导入服务（任务 C-03）：库内校验 + 写库 + ingestion_jobs 审计。

分层（两层校验都要过，谁都不省）：
  - `scripts/validate_data.py`：文件结构校验（CI 的 data-check 门禁，B 交付前自检）
  - 本模块：库内校验（来源/证据外键存在性、重复编号、非法年份、空原文、占位符）+ 事务写入
规则同源于 docs/data-dictionary.md 第 5 节；任一记录不通过则整体不写入。

写库入口只有 `POST /api/admin/import`（契约第 9 节），
因此 scripts/import_data.py、服务器手工导入、将来的人工审核工具都走同一条写库路径。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import (
    CorpusSearch,
    Evidence,
    EvidenceSource,
    IngestionJob,
    MigrationEvent,
    MigrationEventEvidence,
    Place,
    SourceEdition,
    SourceWork,
    Surname,
)
from ..models.enums import (
    CONFIDENCE,
    EVIDENCE_TYPE,
    INGESTION_STAGE,
    LICENSE_STATUS,
    LOCATION_STATUS,
    PUBLISHABLE_VERIFICATION_STATUS,
    RELATION_STATUS,
    WORK_TYPE,
)
from ..timeutil import parse_iso8601, to_iso8601, utcnow

REPO_ROOT = Path(__file__).resolve().parents[3]

# 只允许导入这两个数据文件与 data/verified/ 下的文件：
# data/raw/ 与 data/cleaned/ 永远进不了数据库（AGENTS.md 铁律 2）
STANDALONE_INPUTS = ("data/source_register.csv", "data/corpus_searches.csv")
VERIFIED_DIR = "data/verified"

CODE_PATTERNS = {
    "evidence_code": re.compile(r"^EV-[A-Z-]+-\d{3}$"),
    "migration_code": re.compile(r"^MG-[A-Z-]+-\d{3}$"),
    "search_code": re.compile(r"^CS-[A-Z-]+-\d{3}$"),
    "source_code": re.compile(r"^SRC-\d{3}$"),
}
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
URL = re.compile(r"^https?://\S+$")
PLACEHOLDER = re.compile(r"<[^>]*>|待填|TODO|PLACEHOLDER|占位|(?:^|[:：])\s*示例[:：]?")
BAD_VOLUME = re.compile(r"^(见原文|同上|如前|略|无|不详)$")
EMPTY_EXCERPT = re.compile(r"^[\s.。·…⋯]*$")


@dataclass
class RowIssue:
    """一条可读的导入错误：行号 + 字段 + 原因（契约第 9 节的 errors 元素）。"""

    row: int
    reason: str
    field: str | None = None

    def as_dict(self) -> dict:
        return {"row": self.row, "field": self.field, "reason": self.reason}


@dataclass
class ImportOutcome:
    job_id: str
    stage: str
    total: int
    accepted: int
    rejected: int
    errors: list[dict]
    rolled_back: bool
    started_at: str
    finished_at: str
    dry_run: bool = False  # 便于脚本与测试判断；不进接口响应（契约没有这个字段）

    def as_dict(self) -> dict:
        """严格按契约第 9 节返回，不加临时字段。"""
        return {
            "job_id": self.job_id,
            "stage": self.stage,
            "total": self.total,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "errors": self.errors,
            "rolled_back": self.rolled_back,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------- 路径与文件


def resolve_input_ref(input_ref: str, root: Path | None = None) -> Path:
    """把 input_ref 解析成仓库内的真实文件路径，越界即拒绝。

    允许：data/source_register.csv、data/corpus_searches.csv、data/verified/*.csv。
    拒绝：data/raw/**、data/cleaned/**、绝对路径、`..` 跳出仓库、非 CSV 文件。
    """
    base = (root or REPO_ROOT).resolve()
    candidate = (input_ref or "").strip().replace("\\", "/")
    if not candidate:
        raise ApiError(422, "VALIDATION_ERROR", "input_ref 不能为空", {"field": "input_ref"})
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise ApiError(422, "VALIDATION_ERROR", "input_ref 必须是仓库内的相对路径", {"input_ref": input_ref})

    resolved = (base / candidate).resolve()
    try:
        relative = resolved.relative_to(base).as_posix()
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "input_ref 超出仓库范围", {"input_ref": input_ref}) from None

    # 大小写不敏感：Windows 用户的文件名常见 .CSV；目录大小写不同名实为同一目录
    normalized = relative.lower()
    allowed = normalized in STANDALONE_INPUTS or (
        normalized.startswith(f"{VERIFIED_DIR}/") and normalized.endswith(".csv")
    )
    if not allowed:
        under_verified = normalized.startswith(f"{VERIFIED_DIR}/")
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            (
                f"{relative} 不是 CSV 文件：data/verified/ 下只接受 .csv（数据字典第 5 节）"
                if under_verified
                else "只允许导入 data/source_register.csv、data/corpus_searches.csv 与 data/verified/ 下的 CSV；"
                "候选与清洗数据（data/raw/、data/cleaned/）必须人工回看原文后才能进入 data/verified/（AGENTS.md 铁律 2）"
            ),
            {"input_ref": input_ref, "resolved": relative},
        )
    if not resolved.is_file():
        raise ApiError(422, "VALIDATION_ERROR", f"文件不存在：{relative}", {"input_ref": input_ref})
    return resolved


def read_rows(path: Path) -> list[dict[str, str]]:
    """读取 CSV（兼容 UTF-8 BOM），每行附加 __line 记录真实行号。

    编码与读取失败必须变成**可读的接口错误**：B 用 Excel 存成 GBK 是最常见的情况，
    不允许它变成一个 500（探测实测：改前经管理接口返回 500 INTERNAL_ERROR）。
    提示口径与 scripts/validate_data.py 的“编码错误（请保存为 UTF-8）”一致。
    """
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows: list[dict[str, str]] = []
            for index, raw in enumerate(reader, start=2):
                if not any((value or "").strip() for value in raw.values()):
                    continue
                row = {(key or "").strip(): (value or "").strip() for key, value in raw.items()}
                row["__line"] = str(index)
                rows.append(row)
            return rows
    except UnicodeDecodeError as exc:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "文件编码不是 UTF-8：请在 Excel 里另存为「CSV UTF-8」（带 BOM 也可以），"
            "或先运行 python scripts/validate_data.py 自检（data-pipeline.md 第 3 节）",
            {"input_ref": path.name, "reason": str(exc)[:120]},
        ) from None
    except OSError as exc:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"文件无法读取：{str(exc)[:120]}",
            {"input_ref": path.name},
        ) from None


# ---------------------------------------------------------------- 字段校验小工具


def _issue(row: dict, field: str | None, reason: str) -> RowIssue:
    return RowIssue(row=int(row["__line"]), field=field, reason=reason)


def _require(row: dict, field: str, issues: list[RowIssue]) -> str:
    value = row.get(field, "")
    if not value:
        issues.append(_issue(row, field, "不能为空"))
    return value


def _check_required_text(row: dict, field: str, issues: list[RowIssue]) -> None:
    """必填文本：非空 + 不含占位符。"""
    if _require(row, field, issues):
        value = row[field]
        if PLACEHOLDER.search(value):
            issues.append(_issue(row, field, f"含占位符或示例标记，不能进入已核对数据：{value!r}"))


def _check_code(row: dict, field: str, issues: list[RowIssue]) -> None:
    value = row.get(field, "")
    pattern = CODE_PATTERNS[field]
    if value and not pattern.match(value):
        issues.append(_issue(row, field, f"编号不符合规则（应匹配 {pattern.pattern}）"))


def _check_enum(row: dict, field: str, allowed: tuple[str, ...], issues: list[RowIssue]) -> None:
    value = row.get(field, "")
    if value and value not in allowed:
        issues.append(_issue(row, field, f"取值 {value!r} 不合法，可选：{', '.join(allowed)}"))


def _check_year(row: dict, field: str, issues: list[RowIssue]) -> int | None:
    value = row.get(field, "")
    if not value:
        return None
    if not re.match(r"^-?\d+$", value):
        issues.append(_issue(row, field, f"{value!r} 必须是整数年（公元前为负数），不精确时留空并填 time_label"))
        return None
    return int(value)


def _check_iso8601(row: dict, field: str, issues: list[RowIssue]) -> None:
    value = row.get(field, "")
    if value and not ISO_UTC.match(value):
        issues.append(_issue(row, field, f"必须是 ISO 8601 UTC（如 2026-10-17T03:21:00Z），当前 {value!r}"))


# ---------------------------------------------------------------- 查找与创建


def _get_or_create_surname(session: Session, cache: dict[str, Surname], name: str) -> Surname:
    if name in cache:
        return cache[name]
    existing = session.scalar(select(Surname).where(Surname.canonical_name == name))
    if existing is None:
        # 复姓按字数判定（单字为单姓，多字为复姓）；分类有误由 B 改数据后重新导入
        existing = Surname(canonical_name=name, category="single" if len(name) == 1 else "compound", status="draft")
    cache[name] = existing
    return existing


def _all_by_code(session: Session, model, column) -> dict[str, object]:
    return {value: obj for value, obj in session.execute(select(column, model)).all()}


# ---------------------------------------------------------------- 各文件导入
# 各函数只把待写对象放进 pending 并计数，不直接 commit；
# 全部行通过后才由 import_file 一次性 add_all + flush，因此天然是“整体成功或整体不写入”。


def _stage_source_register(session: Session, rows: list[dict], issues: list[RowIssue]) -> tuple[list, int]:
    """source_register.csv → source_works + source_editions（B-01 的登记表）。"""
    works: dict[tuple[str, str], SourceWork] = {}
    editions: dict[str, SourceEdition] = _all_by_code(session, SourceEdition, SourceEdition.source_code)
    pending: list = []
    accepted = 0

    for row in rows:
        before = len(issues)
        _check_code(row, "source_code", issues)
        for field in ("source_code", "work_title", "work_author", "source_provider", "accessed_at"):
            _check_required_text(row, field, issues)
        _check_enum(row, "work_type", WORK_TYPE, issues)
        _check_enum(row, "license_status", LICENSE_STATUS, issues)
        _check_iso8601(row, "accessed_at", issues)

        code = row.get("source_code", "")
        url = row.get("source_url", "")
        if url and not URL.match(url):
            issues.append(_issue(row, "source_url", f"必须是以 http/https 开头的链接，当前 {url!r}"))
        if not url and not row.get("notes"):
            issues.append(_issue(row, "notes", "source_url 为空时必须说明原因（如纸本、无公开链接）"))
        if code and code in editions:
            issues.append(_issue(row, "source_code", f"来源编号 {code!r} 已入库，不允许重复导入"))
        if len(issues) > before:
            continue

        key = (row["work_title"], row["work_author"])
        work = works.get(key)
        if work is None:
            work = session.scalar(
                select(SourceWork).where(SourceWork.title == row["work_title"], SourceWork.author == row["work_author"])
            )
            if work is None:
                work = SourceWork(
                    title=row["work_title"],
                    author=row["work_author"],
                    dynasty=row.get("dynasty") or None,
                    work_type=row["work_type"],
                )
            works[key] = work

        edition = SourceEdition(
            work=work,
            source_code=code,
            edition=row.get("edition") or None,
            publisher=row.get("publisher") or None,
            source_provider=row["source_provider"],
            source_url=url or None,
            license_status=row["license_status"],
            link_status="ok",
            accessed_at=parse_iso8601(row.get("accessed_at")),
            content_hash=row.get("content_hash") or None,
            notes=row.get("notes") or None,
        )
        editions[code] = edition
        pending.append(edition)
        accepted += 1

    return pending, accepted


def _stage_evidences(session: Session, rows: list[dict], issues: list[RowIssue]) -> tuple[list, int]:
    """evidences.csv → surnames + evidences + evidence_sources。"""
    surnames: dict[str, Surname] = {}
    editions: dict[str, SourceEdition] = _all_by_code(session, SourceEdition, SourceEdition.source_code)
    known_codes = set(session.scalars(select(Evidence.evidence_code)))
    seen_codes: dict[str, int] = {}
    fingerprints: dict[tuple[str, str, str], int] = {}
    pending: list = []
    accepted = 0

    for row in rows:
        before = len(issues)
        _check_code(row, "evidence_code", issues)
        for field in (
            "evidence_code",
            "surname",
            "claim_text",
            "work_title",
            "work_author",
            "volume_or_section",
            "original_excerpt",
            "source_code",
            "accessed_at",
            "verified_by",
            "verification_note",
        ):
            _check_required_text(row, field, issues)
        _check_enum(row, "evidence_type", EVIDENCE_TYPE, issues)
        _check_enum(row, "confidence", CONFIDENCE, issues)
        _check_iso8601(row, "accessed_at", issues)

        status = row.get("verification_status", "")
        if not status:
            issues.append(_issue(row, "verification_status", "不能为空"))
        elif status == "pending":
            issues.append(
                _issue(
                    row,
                    "verification_status",
                    "pending 的记录只能留在 data/raw/，必须回看原文后才能进入 data/verified/（AGENTS.md 铁律 2）",
                )
            )
        elif status not in PUBLISHABLE_VERIFICATION_STATUS:
            issues.append(
                _issue(
                    row,
                    "verification_status",
                    f"取值 {status!r} 不合法，可选：{', '.join(PUBLISHABLE_VERIFICATION_STATUS)}",
                )
            )

        code = row.get("evidence_code", "")
        if code:
            if code in known_codes:
                issues.append(_issue(row, "evidence_code", f"证据编号 {code!r} 已入库（重复证据），不允许重复导入"))
            elif code in seen_codes:
                issues.append(_issue(row, "evidence_code", f"同一文件内证据编号重复（第 {seen_codes[code]} 行已用过）"))
            else:
                seen_codes[code] = int(row["__line"])

        source_code = row.get("source_code", "")
        if source_code and source_code not in editions:
            issues.append(
                _issue(row, "source_code", f"来源版本 {source_code!r} 不存在：先导入 data/source_register.csv（B-01）")
            )

        if not row.get("source_url") and not row.get("access_note"):
            issues.append(_issue(row, None, "source_url 与 access_note 至少填写一项（说明来源或无法提供链接的原因）"))
        url = row.get("source_url", "")
        if url and not URL.match(url):
            issues.append(_issue(row, "source_url", f"必须是 http/https 链接，当前 {url!r}"))

        volume = row.get("volume_or_section", "")
        if volume and BAD_VOLUME.match(volume):
            issues.append(_issue(row, "volume_or_section", f"{volume!r} 无法用于核验，必须写具体卷次、章节或页码"))

        excerpt = row.get("original_excerpt", "")
        if excerpt and EMPTY_EXCERPT.match(excerpt):
            issues.append(_issue(row, "original_excerpt", "只有省略号，等于没有摘录"))

        start = _check_year(row, "year_start", issues)
        end = _check_year(row, "year_end", issues)
        if start is not None and end is not None and start > end:
            issues.append(_issue(row, "year_start", f"year_start({start}) 不能大于 year_end({end})"))

        group = row.get("dispute_group", "")
        if status == "disputed" and not group:
            issues.append(
                _issue(row, "dispute_group", "verification_status=disputed 时必须填写 dispute_group（同组多说法共用）")
            )

        fingerprint = (row.get("surname", ""), row.get("work_title", ""), volume, excerpt[:60])
        if fingerprint[0] and fingerprint[3]:
            if fingerprint in fingerprints:
                issues.append(_issue(row, None, f"与第 {fingerprints[fingerprint]} 行重复：同一姓氏、同一卷次、相同摘录"))
            else:
                fingerprints[fingerprint] = int(row["__line"])

        if len(issues) > before:
            continue

        surname = _get_or_create_surname(session, surnames, row["surname"])
        if surname.status == "draft":
            surname.status = "published"  # 有可展示证据后置为 published（契约第 4 节的 status）
        edition = editions[source_code]
        if url and not edition.source_url:
            edition.source_url = url  # 登记表未填链接、数据行填了，用数据行的（不覆盖已有链接）
        if edition.accessed_at is None:
            edition.accessed_at = parse_iso8601(row.get("accessed_at"))

        evidence = Evidence(
            evidence_code=code,
            surname=surname,
            evidence_type=row["evidence_type"],
            claim_text=row["claim_text"],
            original_excerpt=excerpt,
            volume_or_section=volume,
            time_label=row.get("time_label") or None,
            year_start=start,
            year_end=end,
            verification_status=status,
            confidence=row["confidence"],
            verified_by=row["verified_by"],
            verification_note=row["verification_note"],
            dispute_group=group or None,
        )
        pending.append(evidence)
        pending.append(
            EvidenceSource(
                evidence=evidence,
                source_edition=edition,
                citation_detail=row.get("access_note") or None,
                page_or_location=row.get("page_or_location") or None,
                # CSV 未提供支持方式，留空而不是替 B 猜一个（数据真实性）
                support_type=None,
            )
        )
        accepted += 1

    return pending, accepted


def _stage_places(session: Session, rows: list[dict], issues: list[RowIssue]) -> tuple[list, int]:
    """places.csv → places。"""
    pending: list = []
    accepted = 0

    for row in rows:
        before = len(issues)
        _check_required_text(row, "historical_name", issues)
        _check_enum(row, "location_status", LOCATION_STATUS, issues)
        _require(row, "location_status", issues)
        location_status = row.get("location_status", "")
        coordinates = row.get("coordinates", "")
        if location_status == "unlocatable" and coordinates:
            issues.append(_issue(row, "coordinates", "location_status=unlocatable 时不得填写坐标（不伪造精确坐标）"))
        if location_status in {"unlocatable", "approximate"} and not row.get("location_note"):
            issues.append(_issue(row, "location_note", "无法精确定位时必须说明依据（location_note）"))
        if len(issues) > before:
            continue

        historical = row["historical_name"]
        period = row.get("period") or None
        existing = session.scalar(select(Place).where(Place.historical_name == historical, Place.period == period))
        if existing is not None:
            accepted += 1  # 已存在视为通过，不重复写入
            continue

        pending.append(
            Place(
                historical_name=historical,
                modern_name=row.get("modern_name") or None,
                period=period,
                coordinates=coordinates or None,
                location_status=location_status,
                location_note=row.get("location_note") or None,
            )
        )
        accepted += 1

    return pending, accepted


def _find_or_create_place(
    session: Session,
    cache: dict[tuple[str, str], Place],
    *,
    historical_name: str,
    modern_name: str | None,
    location_status: str,
    coordinates: str | None,
) -> Place:
    key = (historical_name, location_status)
    if key in cache:
        return cache[key]
    existing = session.scalar(
        select(Place).where(Place.historical_name == historical_name, Place.location_status == location_status)
    )
    place = existing or Place(
        historical_name=historical_name,
        modern_name=modern_name or None,
        period=None,  # migrations.csv 没有时期列，不替 B 猜
        coordinates=coordinates or None,
        location_status=location_status,
        location_note=None,
    )
    cache[key] = place
    return place


def _stage_migrations(session: Session, rows: list[dict], issues: list[RowIssue]) -> tuple[list, int]:
    """migrations.csv → migration_events + migration_event_evidences（含两侧地点）。"""
    surnames: dict[str, Surname] = {}
    places: dict[tuple[str, str], Place] = {}
    evidences: dict[str, Evidence] = _all_by_code(session, Evidence, Evidence.evidence_code)
    known_codes = set(session.scalars(select(MigrationEvent.migration_code)))
    seen_codes: set[str] = set()
    pending: list = []
    accepted = 0

    for row in rows:
        before = len(issues)
        _check_code(row, "migration_code", issues)
        for field in (
            "migration_code",
            "surname",
            "time_label",
            "from_historical_name",
            "to_historical_name",
            "event_summary",
            "verified_by",
            "verification_note",
        ):
            _check_required_text(row, field, issues)
        _check_enum(row, "relation_status", RELATION_STATUS, issues)
        _check_enum(row, "confidence", CONFIDENCE, issues)

        for side in ("from", "to"):
            _check_enum(row, f"{side}_location_status", LOCATION_STATUS, issues)
            _require(row, f"{side}_location_status", issues)
            if row.get(f"{side}_location_status") == "unlocatable" and row.get(f"{side}_coordinates"):
                issues.append(_issue(row, f"{side}_coordinates", "unlocatable 时不得填写坐标"))

        code = row.get("migration_code", "")
        if code:
            if code in known_codes:
                issues.append(_issue(row, "migration_code", f"迁徙编号 {code!r} 已入库，不允许重复导入"))
            elif code in seen_codes:
                issues.append(_issue(row, "migration_code", f"同一文件内迁徙编号重复：{code!r}"))
            else:
                seen_codes.add(code)

        start = _check_year(row, "year_start", issues)
        end = _check_year(row, "year_end", issues)
        if start is not None and end is not None and start > end:
            issues.append(_issue(row, "year_start", f"year_start({start}) 不能大于 year_end({end})"))

        codes = [item.strip() for item in re.split(r"[;；]", row.get("evidence_codes", "")) if item.strip()]
        if not codes:
            issues.append(_issue(row, "evidence_codes", "不能为空：迁徙事件必须有证据支持"))
        for evidence_code in codes:
            if not CODE_PATTERNS["evidence_code"].match(evidence_code):
                issues.append(_issue(row, "evidence_codes", f"{evidence_code!r} 不符合证据编号规则"))
            elif evidence_code not in evidences:
                issues.append(_issue(row, "evidence_codes", f"{evidence_code!r} 不在库中：先导入 data/verified/evidences.csv"))

        if len(issues) > before:
            continue

        event = MigrationEvent(
            migration_code=code,
            surname=_get_or_create_surname(session, surnames, row["surname"]),
            from_place=_find_or_create_place(
                session,
                places,
                historical_name=row["from_historical_name"],
                modern_name=row.get("from_modern_name"),
                location_status=row["from_location_status"],
                coordinates=row.get("from_coordinates") or None,
            ),
            to_place=_find_or_create_place(
                session,
                places,
                historical_name=row["to_historical_name"],
                modern_name=row.get("to_modern_name"),
                location_status=row["to_location_status"],
                coordinates=row.get("to_coordinates") or None,
            ),
            time_label=row["time_label"],
            year_start=start,
            year_end=end,
            event_summary=row["event_summary"],
            relation_status=row["relation_status"],
            confidence=row["confidence"],
            verified_by=row["verified_by"],
            verification_note=row["verification_note"],
        )
        pending.append(event)
        for evidence_code in codes:
            pending.append(
                MigrationEventEvidence(
                    migration_event=event,
                    evidence=evidences[evidence_code],
                    # CSV 未提供关系类型，留空而不是猜“直接证据”
                    relation_type=None,
                )
            )
        accepted += 1

    return pending, accepted


def _stage_corpus_searches(session: Session, rows: list[dict], issues: list[RowIssue]) -> tuple[list, int]:
    """corpus_searches.csv → corpus_searches（B-05 的语料审计）。"""
    surnames: dict[str, Surname] = {}
    known_codes = set(session.scalars(select(CorpusSearch.search_code)))
    seen_codes: set[str] = set()
    pending: list = []
    accepted = 0

    for row in rows:
        before = len(issues)
        _check_code(row, "search_code", issues)
        for field in ("search_code", "surname", "corpus_name", "query_text", "operator", "checked_at", "result_count"):
            _check_required_text(row, field, issues)
        _check_iso8601(row, "checked_at", issues)

        code = row.get("search_code", "")
        if code:
            if code in known_codes:
                issues.append(_issue(row, "search_code", f"语料审计编号 {code!r} 已入库，不允许重复导入"))
            elif code in seen_codes:
                issues.append(_issue(row, "search_code", f"同一文件内语料审计编号重复：{code!r}"))
            else:
                seen_codes.add(code)

        raw_count = row.get("result_count", "")
        count_value: int | None = None
        if raw_count and not re.match(r"^\d+$", raw_count):
            issues.append(_issue(row, "result_count", f"必须是非负整数，当前 {raw_count!r}"))
        elif raw_count:
            count_value = int(raw_count)
        if count_value == 0 and not row.get("no_result_reason"):
            issues.append(_issue(row, "no_result_reason", "结果数为 0 时必须填写原因（这是语料审计的核心字段）"))
        if len(issues) > before:
            continue

        pending.append(
            CorpusSearch(
                search_code=code,
                surname=_get_or_create_surname(session, surnames, row["surname"]),
                corpus_name=row["corpus_name"],
                query_text=row["query_text"],
                checked_at=parse_iso8601(row["checked_at"]),
                result_count=count_value or 0,
                no_result_reason=row.get("no_result_reason") or None,
                operator=row["operator"],
                note=row.get("note") or None,
            )
        )
        accepted += 1

    return pending, accepted


STAGES = {
    "source_register.csv": _stage_source_register,
    "evidences.csv": _stage_evidences,
    "places.csv": _stage_places,
    "migrations.csv": _stage_migrations,
    "corpus_searches.csv": _stage_corpus_searches,
}


# ---------------------------------------------------------------- 主流程


def next_job_id(session: Session) -> str:
    """JOB-{yyyyMMdd}-{3 位序号}，按 UTC 日期编号（data-dictionary.md 第 4 节）。"""
    prefix = f"JOB-{datetime.now(UTC).strftime('%Y%m%d')}-"
    last = session.scalar(
        select(IngestionJob.job_id)
        .where(IngestionJob.job_id.like(f"{prefix}%"))
        .order_by(IngestionJob.job_id.desc())
        .limit(1)
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:03d}"


def import_file(
    session: Session,
    *,
    input_ref: str,
    operator: str,
    stage: str = "load",
    dry_run: bool = True,
    root: Path | None = None,
) -> ImportOutcome:
    """校验并把一个数据文件写入数据库；任一记录不通过则整体不写入。

    accepted 表示“校验通过的记录数”；dry_run 时只校验不写库，因此它表示“将要写入多少条”。
    """
    if stage not in INGESTION_STAGE:
        raise ApiError(422, "VALIDATION_ERROR", f"stage 取值 {stage!r} 不合法", {"stage": stage})

    path = resolve_input_ref(input_ref, root)
    handler = STAGES.get(path.name.lower())
    if handler is None:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"不支持的文件：{path.name}（支持 {', '.join(sorted(STAGES))}）",
            {"input_ref": input_ref},
        )

    started = utcnow()
    job_id = next_job_id(session)
    rows = read_rows(path)
    issues: list[RowIssue] = []
    pending, accepted = handler(session, rows, issues)

    write_failed = False
    if not issues and not dry_run:
        try:
            session.add_all(pending)
            session.flush()
        except SQLAlchemyError as exc:
            session.rollback()
            issues = [RowIssue(row=0, reason=f"写库失败，已整体回滚：{str(exc)[:200]}")]
            accepted = 0
            write_failed = True

    rejected = len(rows) if write_failed else len({issue.row for issue in issues if issue.row > 0})
    finished = utcnow()
    job = IngestionJob(
        job_id=job_id,
        source=path.name,
        stage=stage,
        input_ref=input_ref.replace("\\", "/"),
        operator=operator,
        dry_run=dry_run,
        total=len(rows),
        accepted=accepted,
        rejected=rejected,
        rolled_back=bool(issues) and not dry_run,
        error_log=[issue.as_dict() for issue in issues] or None,
        started_at=started,
        finished_at=finished,
    )
    session.add(job)
    session.commit()

    return ImportOutcome(
        job_id=job_id,
        stage=stage,
        total=len(rows),
        accepted=accepted,
        rejected=rejected,
        errors=[issue.as_dict() for issue in issues],
        rolled_back=job.rolled_back,
        started_at=to_iso8601(started),
        finished_at=to_iso8601(finished),
        dry_run=dry_run,
    )
