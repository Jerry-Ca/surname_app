#!/bin/sh
# 停止服务（执行清单 §二）：只 kill 自己 PID 文件里的进程；禁止 killall / pkill -f。
set -eu
cd "$(dirname "$0")/.."

if [ ! -f run/server.pid ]; then
    echo "没有 run/server.pid：本服务可能没在运行（不猜测、不 kill 别人的进程）" >&2
    exit 1
fi
PID="$(cat run/server.pid)"
if ! kill -0 "$PID" 2>/dev/null; then
    echo "PID $PID 已不存在，清理 PID 文件"
    rm -f run/server.pid run/server.port
    exit 0
fi
# 二次确认这个 PID 确实是本项目的服务，避免 PID 被复用后误杀别人的进程。
# 先看命令行（Linux）；拿不到命令行时，用 PID 文件里的端口做 health 确认——两者都不通过就拒绝停止。
ARGS="$(ps -p "$PID" -o args= 2>/dev/null || true)"
if [ -n "$ARGS" ]; then
    case "$ARGS" in
        *app/server.py*) ;;
        *) echo "拒绝停止：PID $PID 的命令行不是本项目的 server.py（$ARGS）" >&2; exit 2 ;;
    esac
else
    PORT="$(cat run/server.port 2>/dev/null || true)"
    if [ -z "$PORT" ]; then
        echo "拒绝停止：拿不到 PID $PID 的命令行，也没有 run/server.port 可核对；请人工确认后再处理。" >&2
        exit 2
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 || {
            echo "拒绝停止：端口 $PORT 上没有响应 /api/health，无法确认 PID $PID 是本服务。" >&2; exit 2; }
    else
        "${PYTHON_BIN:-python3}" - "$PORT" <<'PYEOF' || { echo "拒绝停止：health 未通过，无法确认进程身份。" >&2; exit 2; }
import json, sys, urllib.request
with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/health", timeout=5) as response:
    assert json.load(response)["status"] in {"ok", "degraded"}
PYEOF
    fi
fi
kill "$PID"
for _ in 1 2 3 4 5; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
    echo "PID $PID 仍在运行：把它和 logs/app.log 一起交给 C 排查，不要用 kill -9 扩大影响。" >&2
    exit 1
fi
rm -f run/server.pid run/server.port
echo "已停止 PID $PID"
