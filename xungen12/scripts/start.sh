#!/bin/sh
# 启动服务（执行清单 §二）：只写自己的 PID 文件，不用 sudo、不影响别人。
# 用法：sh scripts/start.sh                 # 默认 18888 —— 站外访问网页的登记端口（页面与 /api 同源）
#       PORT=其他登记端口 sh scripts/start.sh
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
    echo "本机自检：curl http://127.0.0.1:$PORT/api/health"
    echo "站外访问：http://<服务器公网IP>:$PORT/            （网页，静态资源来自 static/）"
    echo "           http://<服务器公网IP>:$PORT/api/health （接口，与网页同源）"
    echo "若站外连不上而本机自检正常：请服务器所有者放行该端口的入站规则（安全组/防火墙）"
else
    echo "启动失败：请看 logs/app.log 的最后几行" >&2
    exit 1
fi
