#!/usr/bin/env bash
# 本地一键启动：后端 8000 + 前端 5173。Windows 请在 Git Bash 中执行。
#
#   bash scripts/dev.sh
#
# 首次使用前请先安装依赖：
#   cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
#   cd frontend && npm install
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 找 Python（venv 优先）
if [[ -x "backend/.venv/Scripts/python.exe" ]]; then
  PY="backend/.venv/Scripts/python.exe"
elif [[ -x "backend/.venv/bin/python" ]]; then
  PY="backend/.venv/bin/python"
else
  PY="$(command -v python || command -v python3)"
fi
echo "使用 Python：$PY"

if [[ ! -f ".env" ]]; then
  echo "未找到 .env，从 .env.example 复制（模型 Key 可留空，系统会进入降级模式）"
  cp .env.example .env
fi

# 数据先自检，避免带着坏数据联调
echo
echo "== 数据自检 =="
"$PY" scripts/validate_data.py --path data || echo "（数据校验未通过，不影响启动，但请在合并前修复）"

echo
echo "== 启动后端 http://127.0.0.1:8000（文档 /docs） =="
(cd backend && "$ROOT/$PY" -m uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!

cleanup() {
  echo
  echo "停止后端（pid $BACKEND_PID）"
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 2
if command -v curl >/dev/null 2>&1; then
  echo "健康检查："
  curl -s http://127.0.0.1:8000/api/health || echo "（后端尚未就绪，稍后重试）"
  echo
fi

echo
echo "== 启动前端 http://127.0.0.1:5173（Ctrl+C 同时停止两端） =="
cd frontend
if [[ ! -d node_modules ]]; then
  echo "未安装前端依赖，正在执行 npm install"
  npm install
fi
npm run dev