#!/usr/bin/env python3
"""数据包校验脚本（任务 C-09 / 执行清单 §1.3）。

用法（在项目目录下）：
    python3 scripts/validate_package.py data/verified/evidences.csv
    python3 scripts/validate_package.py data/verified --all      # 校验目录下全部数据文件
    python3 scripts/validate_package.py backup.json --quiet

退出码：0 通过；1 有错误；2 用法问题。
错误一律是「文件 + 行号 + 字段 + 原因 + 修复建议」，不抛异常栈。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import validation  # noqa: E402

PACKAGE_FILES = ("source_register.csv", "evidences.csv", "migrations.csv", "places.csv", "corpus_searches.csv")


def collect_targets(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        found = [target / name for name in PACKAGE_FILES if (target / name).exists()]
        found += sorted(target.glob("*.json"))
        return found
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="校验数据包（UTF-8/表头/必填/枚举/编号唯一/关联）")
    parser.add_argument("target", help="数据文件或目录（如 data/verified）")
    parser.add_argument("--all", action="store_true", help="目录模式下校验全部已知文件（默认也是全部）")
    parser.add_argument("--quiet", action="store_true", help="只打印汇总")
    args = parser.parse_args()

    target = Path(args.target)
    files = collect_targets(target)
    if not files:
        print(f"没有可校验的数据文件：{target}", file=sys.stderr)
        return 2

    evidence_ids: set[str] = set()
    for path in files:
        if validation.FILENAME_KIND.get(path.name.lower()) == "evidences":
            evidence_ids |= validation.collect_evidence_ids(path)

    worst = 0
    total_rows = 0
    for path in files:
        report = validation.validate_package(path, known_evidence=evidence_ids)
        total_rows += report.rows
        if args.quiet:
            print(f"{path.name}: {report.rows} 条，{'通过' if report.ok() else f'{len(report.errors)} 个错误'}")
        else:
            report.emit()
        worst = max(worst, report.emit() if args.quiet else (0 if report.ok() else 1))

    print(f"\n共 {len(files)} 个文件、{total_rows} 条记录：{'全部通过' if worst == 0 else '存在错误，先修复再导入'}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
