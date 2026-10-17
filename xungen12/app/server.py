#!/usr/bin/env python3
"""标准库 HTTP 服务（任务 C-10）：/api/* 接口 + 静态资源，只用 sqlite3 / http.server。

启动（执行清单 §二，PID 只写自己的）：
    nohup python3 app/server.py --port <登记端口> > logs/app.log 2>&1 & echo $! > run/server.pid

安全约定（执行清单 §四.1.6）：
  - 只绑定命令行给的端口，端口以登记为准，不许与别人冲突；
  - 不暴露目录浏览；数据库文件、.env、logs/、backups/、run/ 一律拒绝；
  - 任何 API 错误都返回 JSON 错误结构，不把异常栈或环境变量扔给调用方。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ask as ask_module  # noqa: E402
from app import contract, db, fts, queries, schema, search  # noqa: E402
from app.paths import DB_PATH, LOGS_DIR, PROJECT_ROOT, SCHEMA_VERSION, SCHEMA_VERSION_FILE, STATIC_DIR  # noqa: E402

SURNAME_PATTERN = re.compile(r"^[\u4e00-\u9fff]{1,8}$")
KINDS = {
    "earliest": "earliest",
    "commanderies": "commanderies",
    "migrations": "migrations",
    "corpus-checks": "corpus-checks",
}
# 静态资源里绝不允许出现的路径片段（数据库、密钥、日志、备份、进程文件）
FORBIDDEN_PARTS = (".db", ".env", ".git", "logs", "backups", "run/", "server.pid")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Handler(BaseHTTPRequestHandler):
    server_version = "xungen12/1.0"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- 基础工具

    def _send_json(self, payload: dict, status: int = 200, cache: str = "no-store") -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _problem(self, problem: contract.ApiProblem) -> None:
        self._send_json(problem.as_payload(), problem.status)

    def _open_db(self) -> sqlite3.Connection:
        if not Path(DB_PATH).exists():
            raise contract.ApiProblem(
                503, contract.DATABASE_UNAVAILABLE,
                "数据库不可用：data/xungen.db 不存在。先运行 python3 scripts/init_db.py",
                {"db_path": str(DB_PATH)},
            )
        try:
            return db.connect(readonly=True)
        except sqlite3.Error as exc:
            raise contract.ApiProblem(
                503, contract.DATABASE_UNAVAILABLE, f"数据库不可用：{type(exc).__name__}", {"db_path": str(DB_PATH)}
            ) from None

    @staticmethod
    def _validate_surname(name: str) -> str:
        candidate = unquote(name or "").strip()
        if not candidate:
            raise contract.ApiProblem(400, contract.INVALID_INPUT, "姓氏输入无效：不能为空", {"reason": "empty"})
        if not SURNAME_PATTERN.match(candidate):
            raise contract.ApiProblem(
                400, contract.INVALID_INPUT, "姓氏输入无效：仅支持 1—8 个汉字",
                {"input": name, "reason": "not_chinese_or_too_long"},
            )
        return candidate

    @staticmethod
    def _paging(query: dict) -> tuple[int, int]:
        try:
            page = int((query.get("page") or ["1"])[0])
            page_size = int((query.get("page_size") or ["20"])[0])
        except ValueError:
            raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "page / page_size 必须是整数") from None
        search._validate_page(page, page_size)
        return page, page_size

    # ---------------------------------------------------------------- 路由

    def do_GET(self) -> None:  # noqa: N802 - http.server 的命名
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/api/health":
                return self._health()
            if path.startswith("/api/"):
                return self._api_get(path, query)
            return self._static(path)
        except contract.ApiProblem as problem:
            self._problem(problem)
        except Exception:  # noqa: BLE001 - 未预期异常：记日志，返回统一 500，不泄露栈
            self._log_traceback()
            self._send_json(
                contract.error(contract.INTERNAL_ERROR, "服务内部错误，请把 logs/app.log 里的时间点提供给 C 排查"), 500
            )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if unquote(parsed.path) == "/api/ask":
                return self._ask()
            raise contract.ApiProblem(404, contract.NOT_FOUND, "请求的接口不存在", {"path": parsed.path})
        except contract.ApiProblem as problem:
            self._problem(problem)
        except Exception:  # noqa: BLE001
            self._log_traceback()
            self._send_json(
                contract.error(contract.INTERNAL_ERROR, "服务内部错误，请把 logs/app.log 里的时间点提供给 C 排查"), 500
            )

    def _api_get(self, path: str, query: dict) -> None:
        if path == "/api/search":
            question = (query.get("q") or [""])[0]
            surname = (query.get("surname") or [None])[0]
            page, page_size = self._paging(query)
            connection = self._open_db()
            try:
                payload = search.search(connection, question, raw_surname=surname, page=page, page_size=page_size)
            finally:
                connection.close()
            return self._send_json(payload)

        parts = [segment for segment in path.split("/") if segment]
        # /api/surnames/{name} 与 /api/surnames/{name}/{kind}
        if len(parts) >= 3 and parts[1] == "surnames":
            name = self._validate_surname(parts[2])
            page, page_size = self._paging(query)
            connection = self._open_db()
            try:
                if len(parts) == 3:
                    payload = queries.overview(connection, name)
                elif len(parts) == 4 and parts[3] in KINDS:
                    payload = queries.category(connection, name, KINDS[parts[3]], page, page_size)
                else:
                    raise contract.ApiProblem(404, contract.NOT_FOUND, "请求的接口不存在", {"path": path})
            finally:
                connection.close()
            return self._send_json(payload, cache="public, max-age=60")

        raise contract.ApiProblem(404, contract.NOT_FOUND, "请求的接口不存在", {"path": path})

    def _health(self) -> None:
        """执行清单 §三.6：status、db、version、model_configured、port；不泄露 Key。"""
        state = {"path": "data/xungen.db", "connected": False, "schema_version": None, "tables": 0, "fts": "n/a"}
        status = "ok"
        http_status = 200
        try:
            connection = self._open_db()
            try:
                state["connected"] = True
                state["schema_version"] = (
                    SCHEMA_VERSION_FILE.read_text(encoding="utf-8").strip() if SCHEMA_VERSION_FILE.exists() else None
                )
                existing = set(db.table_names(connection))
                state["tables"] = len([name for name in schema.TABLES if name in existing])
                state["tables_expected"] = len(schema.TABLES)
                state["fts"] = "ready" if fts.available(connection) else "unavailable"
                db.scalar(connection, "SELECT count(*) FROM evidences")
            finally:
                connection.close()
        except contract.ApiProblem as problem:
            status = "down"
            http_status = 503
            state["error"] = problem.message

        config = ask_module.model_config()
        if status == "ok" and not config["configured"]:
            status = "degraded"
        payload = {
            "status": status,
            "db": state,
            "version": contract.VERSION,
            "model_configured": config["configured"],
            "model": config["model"],
            "port": self.server.server_address[1],
            "checked_at": now_iso(),
        }
        self._send_json(payload, http_status)

    def _ask(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "Content-Length 不正确") from None
        raw = self.rfile.read(min(length, 1_000_000)) if length else b"{}"
        try:
            payload_in = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "请求体不是合法 JSON") from None
        if not isinstance(payload_in, dict):
            raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "请求体必须是 JSON 对象") from None

        question = str(payload_in.get("question") or "")
        surname = payload_in.get("surname")
        if surname is not None:
            surname = self._validate_surname(str(surname))
        evidence_ids = payload_in.get("evidence_ids") or []
        if not isinstance(evidence_ids, list):
            raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "evidence_ids 必须是数组") from None
        top_k_raw = payload_in.get("top_k", ask_module.TOP_K_DEFAULT)
        try:
            top_k = int(top_k_raw)
        except (TypeError, ValueError):
            raise contract.ApiProblem(422, contract.VALIDATION_ERROR, "top_k 必须是整数") from None

        connection = self._open_db()
        try:
            payload = ask_module.ask(
                connection, question=question, surname=surname, evidence_ids=[str(item) for item in evidence_ids], top_k=top_k
            )
        finally:
            connection.close()
        self._send_json(payload, cache="no-store")

    # ---------------------------------------------------------------- 静态资源

    def _static(self, path: str) -> None:
        """只从 static/ 提供 D 的构建产物；其它一律 404，且不做目录浏览。"""
        if not STATIC_DIR.exists():
            raise contract.ApiProblem(404, contract.NOT_FOUND, "静态资源目录不存在（static/），请让 D 提供构建产物")
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        lowered = str(target).lower()
        if any(part in lowered for part in FORBIDDEN_PARTS) or not str(target).startswith(str(STATIC_DIR.resolve())):
            raise contract.ApiProblem(404, contract.NOT_FOUND, "该路径不允许访问", {"path": path})
        if target.is_dir():
            index = target / "index.html"
            if not index.exists():
                raise contract.ApiProblem(404, contract.NOT_FOUND, "不做目录浏览；请访问具体文件", {"path": path})
            target = index
        if not target.exists():
            raise contract.ApiProblem(404, contract.NOT_FOUND, "静态资源不存在", {"path": path})

        content_type = {
            ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
            ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon",
        }.get(target.suffix.lower(), "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log_traceback(self) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[{now_iso()}] 未预期异常：\n{traceback.format_exc()}", flush=True)

    def log_message(self, fmt: str, *args) -> None:  # 统一格式写到 stdout（nohup 会进 logs/app.log）
        print(f"[{now_iso()}] {self.address_string()} {fmt % args}", flush=True)


def serve(port: int, host: str = "0.0.0.0") -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"[{now_iso()}] xungen12 服务启动：http://{host}:{port}（项目目录 {PROJECT_ROOT}，schema v{SCHEMA_VERSION}）", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"[{now_iso()}] 收到中断，停止服务", flush=True)
    finally:
        httpd.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="姓氏寻根系统标准库服务（任务 C-10）")
    parser.add_argument("--port", type=int, required=True, help="监听端口（以服务器登记端口为准）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0（共享服务器上只用登记端口）")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        print(f"端口不合法：{args.port}", file=sys.stderr)
        return 2
    serve(args.port, args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
