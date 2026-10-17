#!/usr/bin/env python3
"""数据校验：检查 data/ 下的 CSV 是否符合 docs/data-dictionary.md 的编号与字段规则。

这是 CI 的 data-check 门禁，也是 B 交付数据前的自检工具。
只做结构与完整性检查，不能替代人工回看原文。

用法：
    python scripts/validate_data.py --path data
    python scripts/validate_data.py --path data --strict     # 把警告当错误
    python scripts/validate_data.py --path data --quiet
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- 枚举（与数据字典同步）

VERIFICATION_STATUS = {"verified", "disputed", "link_stale", "retracted"}
# 只允许出现在 data/raw 的中间状态；出现在 verified/ 就是流程错误
RAW_ONLY_STATUS = {"pending"}
EVIDENCE_TYPE = {"earliest_attestation", "commandery", "migration", "other"}
CONFIDENCE = {"high", "medium", "low"}
RELATION_STATUS = {"agreed", "disputed", "unclear"}
LOCATION_STATUS = {"located", "approximate", "unlocatable"}
WORK_TYPE = {"official_history", "surname_book", "local_gazetteer", "classic", "other"}
LICENSE_STATUS = {"public_domain", "platform_terms_ok", "restricted_excerpt_only", "unknown"}

CODE_PATTERNS = {
    "evidence_code": re.compile(r"^EV-[A-Z-]+-\d{3}$"),
    "migration_code": re.compile(r"^MG-[A-Z-]+-\d{3}$"),
    "search_code": re.compile(r"^CS-[A-Z-]+-\d{3}$"),
    "source_code": re.compile(r"^SRC-\d{3}$"),
}
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
URL = re.compile(r"^https?://\S+$")
# 占位符：绝不允许出现在 verified/ 中
PLACEHOLDER = re.compile(r"<[^>]*>|待填|TODO|PLACEHOLDER|占位|(?:^|[:：])\s*示例[:：]?")
# 无信息量的卷次写法
BAD_VOLUME = re.compile(r"^(见原文|同上|如前|略|无|不详)$")
# 只有省略号的摘录
EMPTY_EXCERPT = re.compile(r"^[\s.。·…⋯]*$")

COLUMNS = {
    "source_register": {
        "required": [
            "source_code", "work_title", "work_author", "work_type",
            "source_provider", "source_url", "license_status", "accessed_at",
        ],
        "optional": ["dynasty", "edition", "publisher", "content_hash", "notes"],
    },
    "corpus_searches": {
        "required": [
            "search_code", "surname", "corpus_name", "query_text",
            "checked_at", "result_count", "no_result_reason", "operator",
        ],
        "optional": ["note"],
    },
    "evidences": {
        "required": [
            "evidence_code", "surname", "evidence_type", "claim_text",
            "work_title", "work_author", "volume_or_section", "original_excerpt",
            "source_code", "accessed_at", "verification_status", "confidence",
            "verified_by", "verification_note",
        ],
        "optional": [
            "dynasty", "page_or_location", "source_url", "access_note",
            "dispute_group", "year_start", "year_end", "time_label",
        ],
        # 二选一：有链接，或说明为何没有链接
        "either": [("source_url", "access_note")],
    },
    "migrations": {
        "required": [
            "migration_code", "surname", "time_label", "from_historical_name",
            "from_location_status", "to_historical_name", "to_location_status",
            "event_summary", "relation_status", "confidence", "evidence_codes",
            "verified_by", "verification_note",
        ],
        "optional": [
            "year_start", "year_end", "from_modern_name", "to_modern_name",
        ],
    },
    "places": {
        "required": ["historical_name", "location_status"],
        "optional": ["modern_name", "period", "coordinates", "location_note"],
    },
}


# ---------------------------------------------------------------- 报告

class Report:
    def __init__(self, quiet: bool = False) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.counts: list[tuple[str, int, str]] = []
        self.quiet = quiet

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def count(self, path: Path, rows: int, note: str = "") -> None:
        self.counts.append((str(path), rows, note))

    def emit(self) -> int:
        print("== 数据校验（docs/data-dictionary.md 规则）==")
        for name, rows, note in self.counts:
            suffix = f"（{note}）" if note else ""
            print(f"  {name:<40} {rows:>5} 条记录{suffix}")
        print("-" * 62)
        if self.warnings and not self.quiet:
            print(f"警告 {len(self.warnings)}：")
            for item in self.warnings:
                print(f"  [WARN] {item}")
        if self.errors:
            print(f"错误 {len(self.errors)}：")
            for item in self.errors:
                print(f"  [FAIL] {item}")
            print(f"结果：不通过（{len(self.errors)} 个错误）")
            return 1
        print(f"结果：通过（警告 {len(self.warnings)} 个）")
        return 0


# ---------------------------------------------------------------- 读取

def read_csv(path: Path, spec_key: str, report: Report) -> tuple[list[str], list[dict[str, str]]]:
    """读取 CSV，返回 (表头, 记录列表)。记录中附加 __line 字段记录行号。"""
    spec = COLUMNS[spec_key]
    try:
        # utf-8-sig：兼容 Excel 导出的带 BOM 文件
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = [h.strip() for h in (reader.fieldnames or [])]
            if not header:
                report.error(str(path), "文件为空或缺少表头")
                return [], []
            missing = [c for c in spec["required"] if c not in header]
            if missing:
                report.error(str(path), f"缺少必需列：{', '.join(missing)}")
            known = set(spec["required"]) | set(spec["optional"]) | {"__line"}
            for column in header:
                if column not in known:
                    report.warn(str(path), f"存在数据字典未定义的列：{column}")
            rows: list[dict[str, str]] = []
            for index, row in enumerate(reader, start=2):
                if not any((value or "").strip() for value in row.values()):
                    continue
                row["__line"] = str(index)
                rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
            return header, rows
    except UnicodeDecodeError as exc:
        report.error(str(path), f"编码错误（请保存为 UTF-8）：{exc}")
        return [], []
    except OSError as exc:
        report.error(str(path), f"无法读取：{exc}")
        return [], []


def require(value: str, path: Path, line: str, field: str, report: Report) -> bool:
    if not value:
        report.error(f"{path}:{line}", f"字段 {field} 不能为空")
        return False
    return True


def check_placeholder(value: str, path: Path, line: str, field: str, report: Report) -> None:
    if value and PLACEHOLDER.search(value):
        report.error(f"{path}:{line}", f"字段 {field} 含占位符或示例标记，不能进入已核对数据：{value!r}")


def check_code(value: str, path: Path, line: str, field: str, report: Report) -> None:
    pattern = CODE_PATTERNS[field]
    if value and not pattern.match(value):
        report.error(f"{path}:{line}", f"{field}={value!r} 不符合编号规则（应匹配 {pattern.pattern}）")


def check_enum(value: str, path: Path, line: str, field: str, allowed: set[str], report: Report) -> None:
    if value and value not in allowed:
        report.error(f"{path}:{line}", f"{field}={value!r} 不是合法取值，可选：{', '.join(sorted(allowed))}")


def check_year(value: str, path: Path, line: str, field: str, report: Report) -> int | None:
    if not value:
        return None
    if not re.match(r"^-?\d+$", value):
        report.error(f"{path}:{line}", f"{field}={value!r} 必须是整数年（公元前为负数）")
        return None
    try:
        return int(value)
    except ValueError:
        return None


# ---------------------------------------------------------------- 各文件校验

def validate_source_register(path: Path, report: Report) -> set[str]:
    _, rows = read_csv(path, "source_register", report)
    known: set[str] = set()
    for row in rows:
        here, line = path, row["__line"]
        code = row.get("source_code", "")
        check_code(code, here, line, "source_code", report)
        require(code, here, line, "source_code", report)
        if code:
            if code in known:
                report.error(f"{here}:{line}", f"来源编号重复：{code}")
            known.add(code)
        for field in ("work_title", "work_author", "source_provider", "accessed_at"):
            if require(row.get(field, ""), here, line, field, report):
                check_placeholder(row[field], here, line, field, report)
        check_enum(row.get("work_type", ""), here, line, "work_type", WORK_TYPE, report)
        check_enum(row.get("license_status", ""), here, line, "license_status", LICENSE_STATUS, report)
        accessed = row.get("accessed_at", "")
        if accessed and not ISO_UTC.match(accessed):
            report.error(f"{here}:{line}", f"accessed_at 必须是 ISO 8601 UTC（如 2026-10-17T03:21:00Z），当前 {accessed!r}")
        url = row.get("source_url", "")
        if url and not URL.match(url):
            report.error(f"{here}:{line}", f"source_url 必须是以 http/https 开头的链接，当前 {url!r}")
        if not url and not row.get("notes", ""):
            report.error(f"{here}:{line}", "source_url 为空时必须在 notes 中说明原因（如纸本、无公开链接）")
    report.count(path, len(rows))
    return known


def validate_corpus_searches(path: Path, report: Report) -> None:
    _, rows = read_csv(path, "corpus_searches", report)
    seen: set[str] = set()
    for row in rows:
        here, line = path, row["__line"]
        code = row.get("search_code", "")
        check_code(code, here, line, "search_code", report)
        if code in seen:
            report.error(f"{here}:{line}", f"语料审计编号重复：{code}")
        seen.add(code)
        for field in ("surname", "corpus_name", "query_text", "operator"):
            require(row.get(field, ""), here, line, field, report)
        checked = row.get("checked_at", "")
        if require(checked, here, line, "checked_at", report) and not ISO_UTC.match(checked):
            report.error(f"{here}:{line}", f"checked_at 必须是 ISO 8601 UTC，当前 {checked!r}")
        raw_count = row.get("result_count", "")
        count_value: int | None = None
        if require(raw_count, here, line, "result_count", report):
            if not re.match(r"^\d+$", raw_count):
                report.error(f"{here}:{line}", f"result_count 必须是非负整数，当前 {raw_count!r}")
            else:
                count_value = int(raw_count)
        if count_value == 0 and not row.get("no_result_reason", ""):
            report.error(f"{here}:{line}", "结果数为 0 时必须填写 no_result_reason（这是语料审计的核心字段）")
    report.count(path, len(rows))


def validate_evidences(path: Path, report: Report, known_sources: set[str]) -> dict[str, str]:
    _, rows = read_csv(path, "evidences", report)
    if rows and not known_sources:
        report.error(
            str(path),
            "已核对证据存在，但 data/source_register.csv 中没有任何来源（B-01 未完成）："
            "每条证据都必须指向一条已登记的来源",
        )
    by_code: dict[str, str] = {}
    dispute_groups: Counter[str] = Counter()
    fingerprints: dict[tuple[str, str, str], str] = {}
    for row in rows:
        here, line = path, row["__line"]
        code = row.get("evidence_code", "")
        check_code(code, here, line, "evidence_code", report)
        if code in by_code:
            report.error(f"{here}:{line}", f"证据编号重复：{code}")
        if code:
            by_code[code] = line
        for field in (
            "surname", "claim_text", "work_title", "work_author",
            "volume_or_section", "original_excerpt", "source_code",
            "accessed_at", "verified_by", "verification_note",
        ):
            value = row.get(field, "")
            if require(value, here, line, field, report):
                check_placeholder(value, here, line, field, report)
        status = row.get("verification_status", "")
        if require(status, here, line, "verification_status", report):
            if status in RAW_ONLY_STATUS:
                report.error(
                    f"{here}:{line}",
                    "verification_status=pending 的记录只能留在 data/raw/，"
                    "必须回看原文后才能进入 data/verified/（AGENTS.md 铁律 2）",
                )
            else:
                check_enum(status, here, line, "verification_status", VERIFICATION_STATUS, report)
        check_enum(row.get("evidence_type", ""), here, line, "evidence_type", EVIDENCE_TYPE, report)
        check_enum(row.get("confidence", ""), here, line, "confidence", CONFIDENCE, report)

        if not row.get("source_url", "") and not row.get("access_note", ""):
            report.error(f"{here}:{line}", "source_url 与 access_note 至少填写一项（说明来源或无法提供链接的原因）")
        url = row.get("source_url", "")
        if url and not URL.match(url):
            report.error(f"{here}:{line}", f"source_url 必须是 http/https 链接，当前 {url!r}")

        source_code = row.get("source_code", "")
        if source_code and known_sources and source_code not in known_sources:
            report.error(f"{here}:{line}", f"source_code={source_code!r} 在 data/source_register.csv 中不存在（先登记来源）")

        accessed = row.get("accessed_at", "")
        if accessed and not ISO_UTC.match(accessed):
            report.error(f"{here}:{line}", f"accessed_at 必须是 ISO 8601 UTC，当前 {accessed!r}")

        volume = row.get("volume_or_section", "")
        if volume and BAD_VOLUME.match(volume):
            report.error(f"{here}:{line}", f"volume_or_section={volume!r} 无法用于核验，必须写具体卷次、章节或页码")

        excerpt = row.get("original_excerpt", "")
        if excerpt:
            if EMPTY_EXCERPT.match(excerpt):
                report.error(f"{here}:{line}", "original_excerpt 只有省略号，等于没有摘录")
            elif len(excerpt) > 2000:
                report.warn(f"{here}:{line}", f"original_excerpt 长度 {len(excerpt)}，超出“短摘录”范围，注意平台条款")

        start = check_year(row.get("year_start", ""), here, line, "year_start", report)
        end = check_year(row.get("year_end", ""), here, line, "year_end", report)
        if start is not None and end is not None and start > end:
            report.error(f"{here}:{line}", f"year_start({start}) 不能大于 year_end({end})")

        group = row.get("dispute_group", "")
        if status == "disputed":
            if not group:
                report.error(f"{here}:{line}", "verification_status=disputed 时必须填写 dispute_group（同组多说法共用）")
            else:
                dispute_groups[group] += 1
        elif group:
            report.warn(f"{here}:{line}", f"非 disputed 记录带有 dispute_group={group!r}，请确认是否有意为之")

        fingerprint = (row.get("surname", ""), row.get("work_title", ""), row.get("volume_or_section", ""), excerpt)
        key = (fingerprint[0], f"{fingerprint[1]}／{fingerprint[2]}", fingerprint[3][:60])
        if key in fingerprints:
            report.error(f"{here}:{line}", f"与 {fingerprints[key]} 重复：同一姓氏、同一卷次、相同摘录")
        else:
            fingerprints[key] = line

    for group, count in dispute_groups.items():
        if count < 2:
            report.warn(f"{path}", f"争议组 {group} 只有 {count} 条记录，争议通常应有多种说法并列")
    report.count(path, len(rows))
    return by_code


def validate_migrations(path: Path, report: Report, known_evidences: dict[str, str]) -> None:
    _, rows = read_csv(path, "migrations", report)
    seen: set[str] = set()
    for row in rows:
        here, line = path, row["__line"]
        code = row.get("migration_code", "")
        check_code(code, here, line, "migration_code", report)
        if code in seen:
            report.error(f"{here}:{line}", f"迁徙编号重复：{code}")
        seen.add(code)
        for field in ("surname", "time_label", "from_historical_name", "to_historical_name", "event_summary",
                      "verified_by", "verification_note"):
            value = row.get(field, "")
            if require(value, here, line, field, report):
                check_placeholder(value, here, line, field, report)
        check_enum(row.get("relation_status", ""), here, line, "relation_status", RELATION_STATUS, report)
        check_enum(row.get("confidence", ""), here, line, "confidence", CONFIDENCE, report)
        for side in ("from", "to"):
            location = row.get(f"{side}_location_status", "")
            check_enum(location, here, line, f"{side}_location_status", LOCATION_STATUS, report)
            coordinates = row.get(f"{side}_coordinates", "")
            if location == "unlocatable" and coordinates:
                report.error(f"{here}:{line}", f"{side}_location_status=unlocatable 时不得填写坐标（不伪造精确坐标）")
            if location == "located" and not coordinates:
                report.warn(f"{here}:{line}", f"{side}_location_status=located 但未提供坐标")
        start = check_year(row.get("year_start", ""), here, line, "year_start", report)
        end = check_year(row.get("year_end", ""), here, line, "year_end", report)
        if start is not None and end is not None and start > end:
            report.error(f"{here}:{line}", f"year_start({start}) 不能大于 year_end({end})")
        codes = [c.strip() for c in re.split(r"[;；]", row.get("evidence_codes", "")) if c.strip()]
        if not codes:
            report.error(f"{here}:{line}", "evidence_codes 不能为空，迁徙事件必须有证据支持")
        for evidence_code in codes:
            check_code(evidence_code, here, line, "evidence_code", report)
            if known_evidences and evidence_code not in known_evidences:
                report.error(f"{here}:{line}", f"evidence_codes 中的 {evidence_code!r} 在 verified/evidences.csv 中不存在")
    report.count(path, len(rows))


def validate_places(path: Path, report: Report) -> None:
    _, rows = read_csv(path, "places", report)
    for row in rows:
        here, line = path, row["__line"]
        require(row.get("historical_name", ""), here, line, "historical_name", report)
        location = row.get("location_status", "")
        check_enum(location, here, line, "location_status", LOCATION_STATUS, report)
        coordinates = row.get("coordinates", "")
        if location == "unlocatable" and coordinates:
            report.error(f"{here}:{line}", "location_status=unlocatable 时不得填写坐标")
        if location in {"unlocatable", "approximate"} and not row.get("location_note", ""):
            report.warn(f"{here}:{line}", "无法精确定位时建议填写 location_note 说明依据")
    report.count(path, len(rows))


# ---------------------------------------------------------------- 主流程

def main() -> int:
    parser = argparse.ArgumentParser(description="校验 data/ 下的 CSV 是否符合数据字典")
    parser.add_argument("--path", default="data", help="数据目录，默认 data")
    parser.add_argument("--strict", action="store_true", help="把警告也视为失败")
    parser.add_argument("--quiet", action="store_true", help="不打印警告明细")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"数据目录不存在：{root}")
        return 1

    report = Report(quiet=args.quiet)

    register = root / "source_register.csv"
    known_sources: set[str] = set()
    if register.exists():
        known_sources = validate_source_register(register, report)
    else:
        report.warn(str(register), "来源登记表不存在，B-01 尚未完成")

    searches = root / "corpus_searches.csv"
    if searches.exists():
        validate_corpus_searches(searches, report)
    else:
        report.warn(str(searches), "语料审计表不存在，B-05 尚未完成")

    verified_dir = root / "verified"
    known_evidences: dict[str, str] = {}
    evidences_path = verified_dir / "evidences.csv"
    if evidences_path.exists():
        known_evidences = validate_evidences(evidences_path, report, known_sources)
    else:
        report.count(evidences_path, 0, "文件不存在，Day1 之前正常")

    migrations_path = verified_dir / "migrations.csv"
    if migrations_path.exists():
        validate_migrations(migrations_path, report, known_evidences)

    places_path = verified_dir / "places.csv"
    if places_path.exists():
        validate_places(places_path, report)

    if report.errors and known_evidences:
        print(f"（已核对证据 {len(known_evidences)} 条）")

    status = report.emit()
    if args.strict and report.warnings:
        print("--strict 已开启：警告视为失败")
        return 1
    return status


if __name__ == "__main__":
    sys.exit(main())