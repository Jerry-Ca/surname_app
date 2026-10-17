#!/bin/sh
# 运行时与目录自检（任务 C-07）：在共享服务器上执行，把输出原文交给 A/组长。
# 用法：sh scripts/runtime_check.sh [端口]
set -u
cd "$(dirname "$0")/.."
PORT="${1:-18888}"
PYTHON_BIN="${PYTHON:-python3}"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="logs/runtime-check-$STAMP.txt"
mkdir -p logs

{
    echo "== 运行时与目录自检（共享服务器）=="
    echo "时间：$(date -u +%Y-%m-%dT%H:%M:%SZ)   目录：$(pwd)"
    echo "-- python3 --version --"
    "$PYTHON_BIN" --version 2>&1 || echo "失败：没有 $PYTHON_BIN（记录原文，联系组长，不要自行安装）"
    echo "-- Python 版本要求（>=3.8）--"
    "$PYTHON_BIN" - <<'PYEOF'
import sys
major, minor = sys.version_info[:2]
print(f"  当前 {major}.{minor}.{sys.version_info.micro}")
if (major, minor) < (3, 8):
    print("  不满足最低要求 3.8：按停线规则记录原文并联系组长，不要自行安装或升级系统 Python")
else:
    print("  满足最低要求 3.8（标准库实现；本机开发环境为 3.12）")
PYEOF
    echo "-- 标准库依赖 --"
    "$PYTHON_BIN" - <<'PYEOF'
import sqlite3, json, csv, http.server, sys
print("Python", sys.version.split()[0])
print("sqlite3 模块", sqlite3.sqlite_version)
connection = sqlite3.connect(":memory:")
try:
    connection.execute("CREATE VIRTUAL TABLE probe USING fts5(x, tokenize='trigram')")
    print("FTS5 + trigram：可用")
except Exception as exc:
    print("FTS5 + trigram：不可用（检索会自动回落 LIKE）", type(exc).__name__)
PYEOF
    echo "-- 目录可写 --"
    for dir in data data/tmp logs run backups; do
        if mkdir -p "$dir" 2>/dev/null && touch "$dir/.write-test" 2>/dev/null; then
            rm -f "$dir/.write-test"; echo "  $dir 可写"
        else
            echo "  $dir 不可写：按停线规则停下，请 A 联系服务器所有者"
        fi
    done
    echo "-- 端口 $PORT --"
    "$PYTHON_BIN" - "$PORT" <<'PYEOF'
import socket, sys
port = int(sys.argv[1])
probe = socket.socket()
try:
    probe.bind(("0.0.0.0", port))
    print(f"  端口 {port} 当前空闲（绑得住）")
except OSError as exc:
    print(f"  端口 {port} 被占用或不可绑：{exc}（换登记端口或记录原文给 A）")
finally:
    probe.close()
PYEOF
    echo "-- 数据库 --"
    if [ -f data/xungen.db ]; then
        echo "  data/xungen.db 已存在（$(du -h data/xungen.db | cut -f1)）"
    else
        echo "  data/xungen.db 不存在：先运行 python3 scripts/init_db.py"
    fi
    echo "== 结束：把本文件原文交给 A/组长 =="
} 2>&1 | tee "$REPORT"

echo
echo "报告已保存：$REPORT"
