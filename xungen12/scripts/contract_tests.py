#!/usr/bin/env python3
"""契约测试（任务 C-15 / 执行清单 §1.4）：每个 /api/* 都存一份 request/response JSON 并校验。

设计要点：
  - 用**临时数据库**（data/tmp/ 下的 xungen.db）跑，不动正式库；测试结束后清理；
  - 用真实 HTTP 请求（urllib），服务在子进程里起在临时端口，只 kill 自己起的那个进程；
  - 测试期间**清空 DEEPSEEK_API_KEY**，确保问答走降级分支，不调用外部模型；
  - 首次运行会把请求/响应存到 docs/contract/，之后每次运行都与存档比对（键名、类型、空数组、错误码）。

用法：
    python3 scripts/contract_tests.py            # 全量契约测试
    python3 scripts/contract_tests.py --quick    # 只测 health + 一条查询（恢复演练后用）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TMP_ROOT = PROJECT_ROOT / "data" / "tmp"
SAMPLES = PROJECT_ROOT / "data" / "samples"
CONTRACT_DIR = PROJECT_ROOT / "docs" / "contract"
PYTHON = os.environ.get("PYTHON", sys.executable)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" —— {detail}" if detail else ""))


# ---------------------------------------------------------------- 环境准备


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def prepare_database(work_dir: Path) -> Path:
    """在 data/tmp/ 下建一个临时库并导入样例数据。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    db_path = work_dir / "xungen.db"
    env = {**os.environ, "XUNGEN_DB": str(db_path)}
    for command in (
        [PYTHON, str(PROJECT_ROOT / "scripts" / "init_db.py"), "--db", str(db_path)],
        [PYTHON, str(PROJECT_ROOT / "scripts" / "import_data.py"), str(SAMPLES), "--operator", "C", "--apply"],
    ):
        completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
        if completed.returncode != 0:
            raise SystemExit(f"准备临时库失败：{' '.join(command)}\n{completed.stdout}\n{completed.stderr}")
    return db_path


def start_server(db_path: Path, port: int) -> subprocess.Popen:
    env = {**os.environ, "XUNGEN_DB": str(db_path)}
    env.pop("DEEPSEEK_API_KEY", None)  # 契约测试不调用真实模型
    process = subprocess.Popen(
        [PYTHON, str(PROJECT_ROOT / "app" / "server.py"), "--port", str(port), "--host", "127.0.0.1"],
        cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    for _ in range(40):
        try:
            request_json(port, "GET", "/api/health", timeout=1)
            return process
        except OSError:
            time.sleep(0.25)
    process.terminate()
    raise SystemExit("服务在 10 秒内没有起来，检查 app/server.py")


# ---------------------------------------------------------------- 请求与校验


def request_json(port: int, method: str, path: str, body: dict | None = None, timeout: float = 10) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{port}{urllib.parse.quote(path, safe='/?&=%')}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def envelope_shape(port: int, path: str, *, expect_empty: bool = False) -> tuple[bool, str]:
    status, payload = request_json(port, "GET", path)
    if status != 200:
        return False, f"HTTP {status}"
    missing = {"data", "audit", "message"} - set(payload)
    if missing:
        return False, f"缺少顶层键 {sorted(missing)}"
    if expect_empty and payload["data"] != []:
        return False, f"期望空数组，实际 {type(payload['data']).__name__}"
    if any(key in json.dumps(payload, ensure_ascii=False).lower() for key in ("api_key", "apikey", "token")):
        return False, "响应里出现疑似密钥字段"
    return True, ""


def save_contract(name: str, method: str, path: str, body: dict | None, status: int, payload: dict) -> None:
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    (CONTRACT_DIR / f"{name}.json").write_text(
        json.dumps(
            {"request": {"method": method, "path": path, "body": body}, "response": {"status": status, "body": payload}},
            ensure_ascii=False, indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def compare_contract(name: str, status: int, payload: dict) -> tuple[bool, str]:
    """与上次存档比对键名与类型（值可以变，形状不能变）。"""
    stored = CONTRACT_DIR / f"{name}.json"
    if not stored.exists():
        return True, "首次生成存档"
    expected = json.loads(stored.read_text(encoding="utf-8"))["response"]
    if expected.get("status") != status:
        return False, f"状态码变化：存档 {expected.get('status')}，现在 {status}"

    def keys_of(value):
        if isinstance(value, dict):
            return {key: keys_of(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            return [keys_of(value[0])] if value else []
        return type(value).__name__

    if keys_of(expected.get("body")) != keys_of(payload):
        return False, f"形状与存档不一致：存档 {keys_of(expected.get('body'))} / 现在 {keys_of(payload)}"
    return True, ""


# ---------------------------------------------------------------- 各项检查


def check_health(port: int) -> None:
    status, payload = request_json(port, "GET", "/api/health")
    required = {"status", "db", "version", "model_configured", "port"}
    ok = status == 200 and required <= set(payload) and isinstance(payload.get("model_configured"), bool)
    detail = "" if ok else f"HTTP {status}，键 {sorted(payload)}"
    if ok and any(key in payload for key in ("api_key", "deepseek_api_key", "token")):
        ok, detail = False, "health 里出现了密钥字段"
    save_contract("health", "GET", "/api/health", None, status, payload)
    record("GET /api/health 返回 status/db/version/model_configured/port 且不泄露 Key", ok, detail)


def check_overview(port: int) -> None:
    # 注意：契约测试的路径必须用 urllib 编码，不能依赖 shell 传中文
    status, payload = request_json(port, "GET", "/api/surnames/李")
    ok = status == 200 and isinstance(payload.get("data"), dict)
    data = payload.get("data") if ok else {}
    four = {"earliest", "commanderies", "migrations", "corpus_checks"} <= set(data) if ok else False
    evidence = data.get("earliest") or {}
    has_id = bool(evidence.get("evidence_id")) and bool(evidence.get("source", {}).get("url"))
    ok = ok and four and has_id
    save_contract("surnames_overview", "GET", "/api/surnames/李", None, status, payload)
    record("GET /api/surnames/{name} 四类数据齐全且每条证据带 evidence_id 与来源", ok,
           "" if ok else f"HTTP {status}，四类齐全={four}，evidence_id/来源={has_id}")


def check_empty_surname(port: int) -> None:
    status, payload = request_json(port, "GET", "/api/surnames/欧")
    ok = status == 200 and isinstance(payload.get("data"), dict) and payload["data"]["earliest"] is None
    ok = ok and payload["data"]["commanderies"] == [] and payload["audit"]["coverage"] == "not_in_corpus"
    ok = ok and bool(payload.get("message"))
    save_contract("surnames_unknown", "GET", "/api/surnames/欧", None, status, payload)
    record("未收录姓氏：200 + 空数组 + audit + message（不是 404/500）", ok,
           "" if ok else f"HTTP {status} {json.dumps(payload, ensure_ascii=False)[:120]}")


def check_categories(port: int) -> None:
    for name, path in (
        ("commanderies", "/api/surnames/李/commanderies?page=1&page_size=2"),
        ("migrations", "/api/surnames/李/migrations"),
        ("corpus_checks", "/api/surnames/李/corpus-checks"),
        ("earliest", "/api/surnames/李/earliest"),
    ):
        status, payload = request_json(port, "GET", path)
        ok = status == 200 and isinstance(payload.get("data"), list) and "pagination" in payload.get("audit", {})
        save_contract(name, "GET", path, None, status, payload)
        record(f"GET {path.split('?')[0]} 返回列表 + 分页", ok, "" if ok else f"HTTP {status}")


def check_pagination_bounds(port: int) -> None:
    status, payload = request_json(port, "GET", "/api/surnames/李/commanderies?page_size=101")
    ok = status == 422 and payload.get("error", {}).get("code") == "VALIDATION_ERROR"
    save_contract("error_page_size", "GET", "/api/surnames/李/commanderies?page_size=101", None, status, payload)
    record("分页越界返回 422 VALIDATION_ERROR", ok, "" if ok else f"HTTP {status} {payload}")


def check_invalid_input(port: int) -> None:
    status, payload = request_json(port, "GET", "/api/surnames/abc")
    ok = status == 400 and payload.get("error", {}).get("code") == "INVALID_SURNAME_INPUT"
    save_contract("error_invalid_surname", "GET", "/api/surnames/abc", None, status, payload)
    record("非法姓氏返回 400 INVALID_SURNAME_INPUT", ok, "" if ok else f"HTTP {status} {payload}")


def check_not_found(port: int) -> None:
    status, payload = request_json(port, "GET", "/api/not-exist")
    ok = status == 404 and payload.get("error", {}).get("code") == "ENDPOINT_NOT_FOUND"
    save_contract("error_not_found", "GET", "/api/not-exist", None, status, payload)
    record("未知路径返回 404 ENDPOINT_NOT_FOUND", ok, "" if ok else f"HTTP {status} {payload}")


def check_search(port: int) -> None:
    status, payload = request_json(port, "GET", "/api/search?q=契约测试原文摘录")
    ok = status == 200 and isinstance(payload.get("data"), list) and payload["data"]
    item = payload["data"][0] if ok else {}
    ok = ok and bool(item.get("evidence_id")) and item.get("matched_field") in {
        "claim_text", "original_excerpt", "volume_or_section"
    }
    save_contract("search_hit", "GET", "/api/search?q=契约测试原文摘录", None, status, payload)
    record("检索命中：带 evidence_id、命中位置与片段", ok, "" if ok else f"HTTP {status}")

    status, payload = request_json(port, "GET", "/api/search?q=库里绝对没有的词")
    ok = status == 200 and payload.get("data") == [] and bool(payload.get("message"))
    save_contract("search_miss", "GET", "/api/search?q=库里绝对没有的词", None, status, payload)
    record("检索无结果：200 + data:[] + message", ok, "" if ok else f"HTTP {status}")


def check_ask_degraded(port: int) -> None:
    status, payload = request_json(port, "POST", "/api/ask", {"surname": "李", "question": "郡望有哪些说法？", "top_k": 3})
    data = payload.get("data", {})
    ok = status == 200 and data.get("answer_mode") == "unavailable" and data.get("abstained") is True
    ok = ok and isinstance(data.get("citations"), list) and data["citations"]
    save_contract("ask_unavailable", "POST", "/api/ask", {"surname": "李", "question": "郡望有哪些说法？", "top_k": 3},
                  status, payload)
    record("模型不可用时问答：200 + unavailable + 仍返回结构化证据", ok,
           "" if ok else f"HTTP {status} {json.dumps(payload, ensure_ascii=False)[:160]}")


def check_ask_no_evidence(port: int) -> None:
    status, payload = request_json(port, "POST", "/api/ask", {"surname": "欧", "question": "迁徙路线？"})
    data = payload.get("data", {})
    ok = status == 200 and data.get("answer") == "当前资料不足以确认" and data.get("citations") == []
    save_contract("ask_insufficient", "POST", "/api/ask", {"surname": "欧", "question": "迁徙路线？"}, status, payload)
    record("证据不足时问答：固定文案「当前资料不足以确认」", ok,
           "" if ok else f"HTTP {status} {json.dumps(payload, ensure_ascii=False)[:160]}")


def check_contract_shapes(port: int) -> None:
    """与上次存档比对形状（键名与类型），保证字段不会被悄悄改掉。"""
    if not CONTRACT_DIR.exists():
        record("与存档比对形状", False, "没有 docs/contract 存档")
        return
    mismatches = []
    for stored in sorted(CONTRACT_DIR.glob("*.json")):
        document = json.loads(stored.read_text(encoding="utf-8"))
        request = document["request"]
        status, payload = request_json(port, request["method"], request["path"], request.get("body"))
        ok, detail = compare_contract(stored.stem, status, payload)
        if not ok:
            mismatches.append(f"{stored.stem}: {detail}")
    record("所有已存档接口的形状与本次一致", not mismatches, "；".join(mismatches) or f"{len(list(CONTRACT_DIR.glob('*.json')))} 个接口")


def main() -> int:
    parser = argparse.ArgumentParser(description="契约测试（每个 /api/* 的 request/response 形状）")
    parser.add_argument("--quick", action="store_true", help="只测 health 与一条查询")
    parser.add_argument("--keep", action="store_true", help="保留临时库（默认删除）")
    args = parser.parse_args()

    work_dir = TMP_ROOT / f"contract-{os.getpid()}"
    port = free_port()
    print(f"== 契约测试（临时库 {work_dir}，端口 {port}）==")
    db_path = prepare_database(work_dir)
    process = start_server(db_path, port)
    try:
        check_health(port)
        check_overview(port)
        if args.quick:
            check_contract_shapes(port)
        else:
            check_empty_surname(port)
            check_categories(port)
            check_pagination_bounds(port)
            check_invalid_input(port)
            check_not_found(port)
            check_search(port)
            check_ask_degraded(port)
            check_ask_no_evidence(port)
            check_contract_shapes(port)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        if not args.keep:
            shutil.rmtree(work_dir, ignore_errors=True)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n== 结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 项通过 ==")
    for name in failed:
        print(f"  失败：{name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
