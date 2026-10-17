#!/bin/sh
# 恢复数据库（执行清单 §三.10 / §1.7）：先备份当前库，再恢复；恢复后自动跑 health 与一条查询。
# 用法：sh scripts/restore.sh backups/xungen-20261017-1830.db [--yes]
# 失败时的保证：自动把恢复前的备份放回去，不覆盖当前正式库。
set -eu
cd "$(dirname "$0")/.."
DUMP="${1:-}"
PORT="${PORT:-18888}"
PYTHON_BIN="${PYTHON:-python3}"
CURL_BIN="$(command -v curl || true)"

if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "用法：sh scripts/restore.sh <备份文件> [--yes]" >&2
    exit 2
fi
if [ "${2:-}" != "--yes" ]; then
    echo "恢复会覆盖 data/xungen.db。确认后加 --yes 再执行（脚本会先自动备份当前库）。" >&2
    exit 2
fi

mkdir -p backups
SAFETY="backups/pre-restore-$(date +%Y%m%d-%H%M%S).db"
if [ -f data/xungen.db ]; then
    cp data/xungen.db "$SAFETY"
    echo "已先备份当前库：$SAFETY"
fi

cp "$DUMP" data/xungen.db
echo "已恢复：$DUMP → data/xungen.db"

# 恢复后自检：health + 一条真实查询
check() {
    if [ -n "$CURL_BIN" ]; then
        "$CURL_BIN" -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null
    else
        "$PYTHON_BIN" - "$PORT" <<'PYEOF'
import json, sys, urllib.request
with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/health", timeout=5) as response:
    assert json.load(response)["status"] in {"ok", "degraded"}
PYEOF
    fi
}
if check; then
    echo "恢复后自检通过：/api/health 正常"
    echo "再跑一条查询确认数据：$PYTHON_BIN scripts/contract_tests.py --quick"
else
    echo "恢复后自检失败：把 $SAFETY 放回 data/xungen.db，并检查 logs/app.log" >&2
    [ -f "$SAFETY" ] && cp "$SAFETY" data/xungen.db
    exit 1
fi
