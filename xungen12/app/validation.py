"""数据包校验核心（任务 C-09）：只依赖标准库，被脚本与测试共用。

规则来源（一处定义，别处只调用）：
  - 执行清单 §一.5 / §1.3：UTF-8、表头、必填字段、状态枚举、证据编号唯一、source_url 格式、关联 evidence_id
  - docs/data-dictionary.md 第 3、5 节：编号规则、枚举、年份区间、占位符、卷次写法
  - app/schema.py：列长度上限与枚举值
每条错误都给**文件 + 行号 + 字段 + 原因 + 修复建议**，不允许只抛一个异常栈。
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import schema

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
URL = re.compile(r"^https?://\S+$")
PLACEHOLDER = re.compile(r"<[^>]*>|待填|TODO|PLACEHOLDER|占位|(?:^|[:：])\s*示例[:：]?")
BAD_VOLUME = re.compile(r"^(见原文|同上|如前|略|无|不详)$")
EMPTY_EXCERPT = re.compile(r"^[\s.。·…⋯]*$")
INTEGER = re.compile(r"^-?\d+$")

# 允许的列名别名：B 的既有数据包用 work_title/work_author/evidence_code，新 schema 用 title/author/evidence_id
FIELD_ALIASES = {
    "evidence_code": "evidence_id",
    "work_title": "source_title",
    "work_author": "source_author",
    "evidence_codes": "evidence_ids",
    "title": "source_title",
    "author": "source_author",
    "name": "surname",
}

REQUIRED: dict[str, tuple[str, ...]] = {
    "evidences": (
        "evidence_id", "surname", "evidence_type", "claim_text", "original_excerpt",
        "volume_or_section", "source_title", "source_author", "source_url", "verification_status", "confidence",
    ),
    "source_register": ("source_code", "source_title", "source_author", "work_type", "license_status"),
    "migrations": (
        "migration_code", "surname", "time_label", "from_historical_name", "from_location_status",
        "to_historical_name", "to_location_status", "event_summary", "relation_status", "confidence", "evidence_ids",
    ),
    "places": ("historical_name", "location_status"),
    "corpus_searches": ("search_code", "surname", "corpus_name", "query_text", "checked_at", "result_count", "operator"),
}

# 各文件（或 JSON 里 kind 字段）与列的对应；列名比对时统一走别名
# 每个种类的全部已知列 = 必需列 + 可选列（必需列只写一次，避免两处列名对不上）
COLUMNS: dict[str, tuple[str, ...]] = {
    "evidences": REQUIRED["evidences"] + (
        "dynasty", "page_or_location", "source_code", "access_note", "accessed_at", "verified_by",
        "verification_note", "dispute_group", "year_start", "year_end", "time_label",
    ),
    "source_register": REQUIRED["source_register"] + (
        "dynasty", "edition", "publisher", "source_provider", "accessed_at", "content_hash", "notes",
    ),
    "migrations": REQUIRED["migrations"] + (
        "year_start", "year_end", "from_modern_name", "to_modern_name", "from_coordinates",
        "to_coordinates", "from_location_note", "to_location_note", "verified_by", "verification_note",
        "relation_type",
    ),
    "places": REQUIRED["places"] + ("modern_name", "period", "coordinates", "location_note"),
    "corpus_searches": REQUIRED["corpus_searches"] + ("no_result_reason", "note"),
}

# 文件名 → 数据种类；JSON 文件用内容里的 kind 字段
FILENAME_KIND = {
    "evidences.csv": "evidences",
    "source_register.csv": "source_register",
    "migrations.csv": "migrations",
    "places.csv": "places",
    "corpus_searches.csv": "corpus_searches",
}

# 核对状态里需要人工署名与说明的（可对外发布的四种）
NEEDS_VERIFIER = ("verified", "disputed", "link_stale", "retracted")


@dataclass
class Issue:
    row: int          # CSV 行号（表头是第 1 行）或 JSON 记录序号（从 1 开始）；0 表示整份文件
    field: str | None
    reason: str
    fix: str = ""

    def as_dict(self) -> dict:
        return {"row": self.row, "field": self.field, "reason": self.reason, "fix": self.fix}

    def __str__(self) -> str:
        where = f"第 {self.row} 行" if self.row else "整份文件"
        target = f"字段 {self.field}" if self.field else "文件"
        return f"{where} {target}：{self.reason}" + (f"（修复：{self.fix}）" if self.fix else "")


@dataclass
class Report:
    kind: str
    path: Path
    rows: int = 0
    issues: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return self.issues

    def ok(self) -> bool:
        return not self.issues

    def emit(self) -> int:
        print(f"== 校验 {self.path.name}（{self.kind}）=")
        print(f"  记录数：{self.rows}")
        for issue in self.warnings:
            print(f"  [警告] {issue}")
        for issue in self.issues:
            print(f"  [错误] {issue}")
        print(f"  {'通过' if self.ok() else f'不通过（{len(self.issues)} 个错误）'}")
        return 0 if self.ok() else 1


def normalize_row(row: dict) -> dict:
    """把别名统一成 schema 里的标准列名（work_title → source_title 等）。"""
    normalized: dict = {}
    for key, value in row.items():
        if key == "__line":
            continue
        canonical = FIELD_ALIASES.get(key, key)
        text = "" if value is None else str(value).strip()
        normalized[canonical] = text
    return normalized


def read_package(path: Path) -> tuple[str, list[dict], list[Issue]]:
    """读取 CSV 或 JSON，返回 (kind, 行列表, 读取层问题)。行里带 __line 记录真实行号。"""
    issues: list[Issue] = []
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".json"}:
        return "", [], [Issue(0, None, f"只接受 .csv 或 .json，收到 {path.suffix}", "用导出脚本重新生成数据包")]

    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        return "", [], [Issue(0, None, f"文件编码不是 UTF-8：{str(exc)[:80]}",
                              "在 Excel 里另存为「CSV UTF-8」，或重新导出为 JSON")]

    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return "", [], [Issue(0, None, f"JSON 解析失败：{exc}", "检查逗号、引号与括号是否配对")]
        records = payload.get("records") if isinstance(payload, dict) else payload
        stem_kind = path.stem.lower() if path.stem.lower() in COLUMNS else ""
        kind = (payload.get("kind") if isinstance(payload, dict) else None) or FILENAME_KIND.get(
            path.name.lower(), stem_kind
        )
        if not isinstance(records, list):
            return kind, [], [Issue(0, None, "JSON 结构不是数组（或缺少 records 数组）",
                                    '顶层用 [ {...}, {...} ] 或 {"kind": "evidences", "records": [ ... ]}')]
        rows = []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                issues.append(Issue(index, None, "记录不是对象", "每条记录写成 {\"字段\": \"值\"}"))
                continue
            row = {key: ("" if value is None else str(value)) for key, value in record.items()}
            row["__line"] = str(index)
            rows.append(row)
        return kind, rows, issues

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = [(column or "").strip() for column in (reader.fieldnames or [])]
        kind = FILENAME_KIND.get(path.name.lower(), "")
        if not kind and header:
            # 按列名猜：有 migration_code 就是迁徙，有 evidence_id/evidence_code 就是证据
            joined = " ".join(FIELD_ALIASES.get(column, column) for column in header)
            for candidate in ("migrations", "evidences", "source_register", "corpus_searches", "places"):
                if all(column in joined.split() for column in REQUIRED[candidate][:2]):
                    kind = candidate
                    break
        duplicates = [column for column in set(header) if header.count(column) > 1]
        if duplicates:
            issues.append(Issue(0, None, f"表头有重复列：{'、'.join(sorted(duplicates))}",
                                "重复列名会让后一列静默覆盖前一列，请改列名"))
        rows = []
        for index, raw in enumerate(reader, start=2):
            if not any((value or "").strip() for value in raw.values()):
                continue
            row = {(key or "").strip(): (value or "").strip() for key, value in raw.items()}
            row["__line"] = str(index)
            rows.append(row)
        return kind, rows, issues


def _require(row: dict, field_name: str, issues: list[Issue]) -> str:
    value = row.get(field_name, "")
    if not value:
        issues.append(Issue(int(row["__line"]), field_name, "不能为空", "从来源处补齐该字段后再导出"))
    return value


def _check_code(row: dict, field_name: str, issues: list[Issue]) -> None:
    value = row.get(field_name, "")
    pattern = schema.CODE_PATTERNS.get(field_name)
    if value and pattern and not re.match(pattern, value):
        issues.append(Issue(int(row["__line"]), field_name, f"编号不符合规则（应匹配 {pattern}）",
                            "按数据字典第 4 节的编号规则重编；编号一经使用不得复用"))


def _check_enum(row: dict, field_name: str, allowed: tuple[str, ...], issues: list[Issue]) -> None:
    value = row.get(field_name, "")
    if value and value not in allowed:
        issues.append(Issue(int(row["__line"]), field_name, f"取值 {value!r} 不合法",
                            f"可选：{'、'.join(allowed)}"))


def _check_lengths(row: dict, table: str, issues: list[Issue]) -> None:
    limits = schema.MAX_LENGTHS.get(table, {})
    for field_name, limit in limits.items():
        value = row.get(field_name, "")
        if len(value) > limit:
            issues.append(Issue(int(row["__line"]), field_name, f"超过 {limit} 字上限：当前 {len(value)} 字",
                                "收敛为短摘录/短字段；原文摘录不要整段粘贴"))


def _check_year(row: dict, field_name: str, issues: list[Issue]) -> int | None:
    value = row.get(field_name, "")
    if not value:
        return None
    if not INTEGER.match(value):
        issues.append(Issue(int(row["__line"]), field_name, f"{value!r} 不是整数年",
                            "公元前用负数（如 -100），不精确时留空并填 time_label"))
        return None
    return int(value)


def _check_placeholder(row: dict, field_name: str, issues: list[Issue]) -> None:
    value = row.get(field_name, "")
    if value and PLACEHOLDER.search(value):
        issues.append(Issue(int(row["__line"]), field_name, f"含占位符或示例标记：{value!r}",
                            "占位数据不得入库；确无内容时留空并说明"))


def _validate_evidences(rows: list[dict], issues: list[Issue]) -> None:
    seen: dict[str, int] = {}
    fingerprints: dict[tuple[str, str, str], int] = {}
    for row in rows:
        line = int(row["__line"])
        for field_name in REQUIRED["evidences"]:
            if _require(row, field_name, issues) and field_name in {
                "claim_text", "original_excerpt", "volume_or_section", "source_title", "source_author",
            }:
                _check_placeholder(row, field_name, issues)
        _check_code(row, "evidence_id", issues)
        _check_enum(row, "evidence_type", schema.EVIDENCE_TYPE, issues)
        _check_enum(row, "confidence", schema.CONFIDENCE, issues)
        _check_enum(row, "verification_status", schema.VERIFICATION_STATUS, issues)
        _check_lengths(row, "evidences", issues)

        evidence_id = row.get("evidence_id", "")
        if evidence_id:
            if evidence_id in seen:
                issues.append(Issue(line, "evidence_id", f"编号重复（第 {seen[evidence_id]} 行已用过）",
                                    "证据编号必须唯一；重复行请合并或重新编号"))
            else:
                seen[evidence_id] = line

        url = row.get("source_url", "")
        if url and not URL.match(url):
            issues.append(Issue(line, "source_url", f"不是 http/https 链接：{url!r}", "填来源链接；纸本等无法提供链接时写 access_note"))
        if not url and not row.get("access_note"):
            issues.append(Issue(line, "source_url", "缺少来源链接且未填 access_note",
                                "有链接填 source_url，无链接在 access_note 说明原因（纸本/无公开链接）"))

        volume = row.get("volume_or_section", "")
        if volume and BAD_VOLUME.match(volume):
            issues.append(Issue(line, "volume_or_section", f"{volume!r} 无法用于核验",
                                "写具体卷次、章节或页码，不要写「见原文」"))
        excerpt = row.get("original_excerpt", "")
        if excerpt and EMPTY_EXCERPT.match(excerpt):
            issues.append(Issue(line, "original_excerpt", "只有省略号，等于没有摘录", "粘贴回看原文得到的短摘录"))

        start = _check_year(row, "year_start", issues)
        end = _check_year(row, "year_end", issues)
        if start is not None and end is not None and start > end:
            issues.append(Issue(line, "year_start", f"year_start({start}) 大于 year_end({end})",
                                "交换或修正年份；不确定就都留空并填 time_label"))

        status = row.get("verification_status", "")
        group = row.get("dispute_group", "")
        if status == "disputed" and not group:
            issues.append(Issue(line, "dispute_group", "有争议的记录必须填 dispute_group",
                                "同组多种说法共用一个 dispute_group，前端要并列展示"))
        if status in NEEDS_VERIFIER:
            if not row.get("verified_by"):
                issues.append(Issue(line, "verified_by", f"{status} 的记录必须有操作人",
                                    "填真实成员代号（如 B）；没有人工回看原文不得标为可发布状态"))
            if not row.get("verification_note"):
                issues.append(Issue(line, "verification_note", f"{status} 的记录必须写核验说明",
                                    "写清核对了什么、哪里存疑"))

        fingerprint = (row.get("surname", ""), row.get("source_title", ""), row.get("volume_or_section", ""))
        if all(fingerprint) and excerpt:
            key = (*fingerprint, excerpt[:60])
            if key in fingerprints:
                issues.append(Issue(line, None, f"与第 {fingerprints[key]} 行疑似重复（同姓氏、同来源、同卷次、同摘录）",
                                    "确认是否重复记录；确为不同事实时把 claim_text 写清"))
            else:
                fingerprints[key] = line


def _validate_source_register(rows: list[dict], issues: list[Issue]) -> None:
    seen: set[str] = set()
    for row in rows:
        line = int(row["__line"])
        for field_name in REQUIRED["source_register"]:
            if _require(row, field_name, issues) and field_name in {"source_title", "source_author"}:
                _check_placeholder(row, field_name, issues)
        _check_code(row, "source_code", issues)
        _check_enum(row, "work_type", schema.WORK_TYPE, issues)
        _check_enum(row, "license_status", schema.LICENSE_STATUS, issues)
        _check_lengths(row, "source_works", issues)
        code = row.get("source_code", "")
        if code:
            if code in seen:
                issues.append(Issue(line, "source_code", f"来源编号重复：{code}", "每个版本一个编号（SRC-nnn）"))
            seen.add(code)
        url = row.get("source_url", "")
        if url and not URL.match(url):
            issues.append(Issue(line, "source_url", f"不是 http/https 链接：{url!r}", "填平台链接或写进 notes 说明" ))
        accessed = row.get("accessed_at", "")
        if accessed and not ISO_UTC.match(accessed):
            issues.append(Issue(line, "accessed_at", f"不是 ISO 8601 UTC：{accessed!r}",
                                "写成 2026-10-17T03:21:00Z 的形式"))


def _validate_migrations(rows: list[dict], issues: list[Issue], known_evidence: set[str]) -> None:
    seen: set[str] = set()
    for row in rows:
        line = int(row["__line"])
        for field_name in REQUIRED["migrations"]:
            if _require(row, field_name, issues) and field_name in {"time_label", "event_summary"}:
                _check_placeholder(row, field_name, issues)
        _check_code(row, "migration_code", issues)
        _check_enum(row, "relation_status", schema.RELATION_STATUS, issues)
        _check_enum(row, "confidence", schema.CONFIDENCE, issues)
        _check_lengths(row, "migration_events", issues)
        code = row.get("migration_code", "")
        if code:
            if code in seen:
                issues.append(Issue(line, "migration_code", f"迁徙编号重复：{code}", "编号必须唯一"))
            seen.add(code)
        for side in ("from", "to"):
            location = row.get(f"{side}_location_status", "")
            _check_enum(row, f"{side}_location_status", schema.LOCATION_STATUS, issues)
            if location == "unlocatable" and row.get(f"{side}_coordinates"):
                issues.append(Issue(line, f"{side}_coordinates", "无法定位时不得填写坐标",
                                    "坐标留空，在 location_note 说明依据"))
        start = _check_year(row, "year_start", issues)
        end = _check_year(row, "year_end", issues)
        if start is not None and end is not None and start > end:
            issues.append(Issue(line, "year_start", f"year_start({start}) 大于 year_end({end})", "修正年份区间"))
        ids = [item.strip() for item in re.split(r"[;；,，]", row.get("evidence_ids", "")) if item.strip()]
        if not ids:
            issues.append(Issue(line, "evidence_ids", "迁徙事件必须挂证据编号", "填该事件依据的 EV-xxx，多个用分号分隔"))
        for evidence_id in ids:
            if not re.match(schema.CODE_PATTERNS["evidence_id"], evidence_id):
                issues.append(Issue(line, "evidence_ids", f"{evidence_id!r} 不是合法证据编号", "按 EV-姓氏-序号 的格式填写"))
            elif known_evidence and evidence_id not in known_evidence:
                issues.append(Issue(line, "evidence_ids", f"{evidence_id!r} 在证据包/库中不存在",
                                    "先导入该证据，或修正编号"))


def _validate_places(rows: list[dict], issues: list[Issue]) -> None:
    for row in rows:
        line = int(row["__line"])
        _require(row, "historical_name", issues)
        _check_enum(row, "location_status", schema.LOCATION_STATUS, issues)
        _require(row, "location_status", issues)
        _check_lengths(row, "places", issues)
        if row.get("location_status") == "unlocatable" and row.get("coordinates"):
            issues.append(Issue(line, "coordinates", "无法定位时不得填写坐标", "留空并在 location_note 说明"))
        if row.get("location_status") in {"unlocatable", "approximate"} and not row.get("location_note"):
            issues.append(Issue(line, "location_note", "无法精确定位时应说明依据", "写清定位依据或为何无法定位"))


def _validate_corpus_searches(rows: list[dict], issues: list[Issue]) -> None:
    seen: set[str] = set()
    for row in rows:
        line = int(row["__line"])
        for field_name in REQUIRED["corpus_searches"]:
            _require(row, field_name, issues)
        _check_code(row, "search_code", issues)
        _check_lengths(row, "corpus_searches", issues)
        code = row.get("search_code", "")
        if code:
            if code in seen:
                issues.append(Issue(line, "search_code", f"语料审计编号重复：{code}", "每次查询一个编号（CS-姓氏-序号）"))
            seen.add(code)
        checked = row.get("checked_at", "")
        if checked and not ISO_UTC.match(checked):
            issues.append(Issue(line, "checked_at", f"不是 ISO 8601 UTC：{checked!r}", "写成 2026-10-17T03:21:00Z"))
        raw_count = row.get("result_count", "")
        count: int | None = None
        if raw_count and not INTEGER.match(raw_count):
            issues.append(Issue(line, "result_count", f"不是整数：{raw_count!r}", "填非负整数"))
        elif raw_count:
            count = int(raw_count)
            if count < 0:
                issues.append(Issue(line, "result_count", "不能为负数", "填非负整数"))
        if count == 0 and not row.get("no_result_reason"):
            issues.append(Issue(line, "no_result_reason", "结果数为 0 时必须写原因",
                                "这是语料审计的核心字段：写清为什么没查到"))


VALIDATORS = {
    "evidences": lambda rows, issues, known: _validate_evidences(rows, issues),
    "source_register": lambda rows, issues, known: _validate_source_register(rows, issues),
    "migrations": lambda rows, issues, known: _validate_migrations(rows, issues, known),
    "places": lambda rows, issues, known: _validate_places(rows, issues),
    "corpus_searches": lambda rows, issues, known: _validate_corpus_searches(rows, issues),
}


def validate_package(path: Path, *, known_evidence: set[str] | None = None, kind: str | None = None) -> Report:
    """校验一个数据文件；known_evidence 用于检查迁徙记录引用的证据是否存在。"""
    detected_kind, raw_rows, issues = read_package(path)
    resolved = kind or detected_kind
    report = Report(kind=resolved or "unknown", path=path, rows=len(raw_rows))
    report.issues.extend(issues)
    if not resolved:
        report.issues.append(Issue(0, None, "无法判断数据种类",
                                   "文件名用 evidences.csv / migrations.csv / places.csv / source_register.csv / corpus_searches.csv，"
                                   "或 JSON 里给 kind 字段"))
        return report

    rows = []
    for raw in raw_rows:
        row = normalize_row(raw)
        row["__line"] = raw["__line"]
        rows.append(row)

    header = set()
    for row in rows:
        header.update(key for key in row if key != "__line")
    missing = [column for column in REQUIRED[resolved] if column not in header]
    if missing:
        report.issues.append(Issue(0, None, f"缺少必需列：{'、'.join(missing)}",
                                   f"列名以 app/schema.py 与 docs/data-dictionary.md 第 5 节为准（{resolved}）"))
        return report

    extra = sorted(header - set(COLUMNS[resolved]))
    for column in extra:
        report.warnings.append(Issue(0, column, "数据包里存在 schema 未定义的列", "会被忽略；如确需保留请先扩 schema"))

    VALIDATORS[resolved](rows, report.issues, known_evidence or set())
    return report


def collect_evidence_ids(path: Path) -> set[str]:
    """从证据包里收集编号（供迁徙校验使用）。"""
    kind, rows, _ = read_package(path)
    if kind not in {"evidences", ""}:
        return set()
    ids = set()
    for raw in rows:
        row = normalize_row(raw)
        if row.get("evidence_id"):
            ids.add(row["evidence_id"])
    return ids
