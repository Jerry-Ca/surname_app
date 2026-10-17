#!/usr/bin/env python3
"""导入已核对数据（任务 C-03 的骨架，B 交付时用它验收）。

设计要点：
  1. 只接受 data/verified/ 下的文件——raw/ 与 cleaned/ 一律拒绝（AGENTS.md 铁律 2、5）
  2. 先跑与 CI 完全相同的数据校验，通过后才会触碰服务器
  3. 写库不直连数据库，而是调用契约里的 POST /api/admin/import，避免出现第二套写库逻辑

用法：
    python scripts/import_data.py --file data/verified/evidences.csv --operator B            # 本地校验（默认干跑）
    python scripts/import_data.py --file data/verified/evidences.csv --operator B --apply \
        --api-url http://127.0.0.1:8000 --token $ADMIN_TOKEN
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_data import (  # noqa: E402
    Report,
    read_csv,
    validate_evidences,
    validate_migrations,
    validate_places,
    validate_source_register,
)

VALIDATORS = {
    "evidences.csv": validate_evidences,
    "migrations.csv": validate_migrations,
    "places.csv": validate_places,
}


def check_location(path: Path) -> None:
    parts = [part.lower() for part in path.parts]
    if "verified" not in parts:
        raise SystemExit(
            f"拒绝导入：{path} 不在 data/verified/ 下。\n"
            "候选与清洗数据只能停留在 data/raw/ 与 data/cleaned/，"
            "必须人工回看原文后才能进入 data/verified/（AGENTS.md 铁律 2）。"
        )


def local_validate(path: Path, data_root: Path) -> tuple[int, Report]:
    report = Report()
    register = data_root / "source_register.csv"
    known_sources: set[str] = set()
    if register.exists():
        known_sources = validate_source_register(register, report)

    name = path.name.lower()
    if name == "evidences.csv":
        rows = validate_evidences(path, report, known_sources)
        count = len(rows)
    elif name in VALIDATORS:
        validator = VALIDATORS[name]
        _, rows = read_csv(path, path.stem, report)
        # migrations 需要 evidence_codes 交叉校验
        known_evidences: dict[str, str] = {}
        evidences_path = path.parent / "evidences.csv"
        if name == "migrations.csv" and evidences_path.exists():
            known_evidences = validate_evidences(evidences_path, report, known_sources)
        if name == "migrations.csv":
            validate_migrations(path, report, known_evidences)
        elif name == "places.csv":
            validate_places(path, report)
        count = len(rows)
    else:
        raise SystemExit(f"不支持的文件：{path.name}（支持 evidences.csv / migrations.csv / places.csv）")
    return count, report


def post_import(api_url: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/admin/import",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Admin-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body)["error"]
            raise SystemExit(f"导入失败（HTTP {error.code} · {detail['code']}）：{detail['message']}") from None
        except (KeyError, json.JSONDecodeError):
            raise SystemExit(f"导入失败（HTTP {error.code}）：{body[:400]}") from None
    except urllib.error.URLError as error:
        raise SystemExit(f"无法连接后端 {api_url}：{error.reason}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 data/verified/ 下的已核对数据")
    parser.add_argument("--file", required=True, help="待导入文件，必须在 data/verified/ 下")
    parser.add_argument("--operator", required=True, help="操作人（写进 ingestion_jobs 与 review_logs）")
    parser.add_argument("--stage", default="load", choices=["verify", "load", "index"])
    parser.add_argument("--data-root", default="data", help="数据根目录，默认 data")
    parser.add_argument("--apply", action="store_true", help="真正写入服务器（默认只做本地校验）")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--token", default="", help="X-Admin-Token，值来自服务器环境变量 ADMIN_TOKEN")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"文件不存在：{path}")
    check_location(path)

    print(f"== 本地校验：{path} ==")
    count, report = local_validate(path, data_root)
    code = report.emit()
    if code != 0:
        print()
        print("本地校验未通过，已中止导入。请修复后重试（校验规则见 docs/data-dictionary.md 第 5 节）。")
        return code
    print(f"本地校验通过：{count} 条记录")

    if not args.apply:
        print()
        print("当前为干跑模式：未触碰服务器。加 --apply 才会调用 POST /api/admin/import。")
        return 0

    if not args.token:
        raise SystemExit("--apply 需要 --token（服务器环境变量 ADMIN_TOKEN 的值）")

    print()
    print("== 提交服务器导入（服务端仍会做一次校验，失败可回滚） ==")
    result = post_import(
        args.api_url,
        args.token,
        {"input_ref": str(path).replace("\\", "/"), "dry_run": False, "operator": args.operator, "stage": args.stage},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("rejected"):
        print()
        print("存在被拒绝的记录，服务端已整体回滚。请按 errors 中的行号修复后重新导入。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())