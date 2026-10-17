#!/bin/sh
# 启动服务（执行清单 §二）：只写自己的 PID 文件，不用 sudo、不影响别人。
# 用法：PORT=18888 sh scripts/start.sh      # 端口以服务器登记端口为准
set -eu
cd "$(dirname "$0")/.."
PORT="${PORT:-18888}"
PYTHON_BIN="${PYTHON:-python3}"

if [ -f run/server.pid ] && kill -0 "$(cat run/server.pid)" 2>/dev/null; then
    echo "已在运行：PID $(cat run/server.pid)（先执行 sh scripts/stop.sh 再启动）" >&2
    exit 1
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "找不到 $PYTHON_BIN：按停线规则记录原文并联系组长，不要自行安装系统包。" >&2
    exit 2
fi
mkdir -p logs run
nohup "$PYTHON_BIN" app/server.py --port "$PORT" > logs/app.log 2>&1 &
PID=$!
echo "$PID" > run/server.pid
echo "$PORT" > run/server.port
sleep 1
if kill -0 "$PID" 2>/dev/null; then
    echo "已启动：PID $PID，端口 $PORT，日志 logs/app.log"
    echo "健康检查：curl http://127.0.0.1:$PORT/api/health"
else
    echo "启动失败：请看 logs/app.log 的最后几行" >&2
    exit 1
fi
