#!/bin/sh
# 恢复数据库（执行清单 §三.10 / §1.7）
#
#   正常恢复：先备份当前库，再覆盖恢复；恢复后跑 health + 一条真实查询；自检失败自动放回原库。
#     sh scripts/restore.sh backups/xungen-20261017-1830.db --yes
#
#   恢复演练：只在 data/tmp/ 里对**临时副本**恢复，跑契约测试，**完全不碰正式库**。
#     sh scripts/restore.sh backups/xungen-20261017-1830.db --drill
set -eu
cd "$(dirname "$0")/.."
DUMP="${1:-}"
PORT="${PORT:-18888}"
PYTHON_BIN="${PYTHON:-python3}"
CURL_BIN="$(command -v curl || true)"

MODE="${2:-}"
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "用法：sh scripts/restore.sh <备份文件> [--yes|--drill]" >&2
    exit 2
fi

# -------- 演练模式：只恢复到 data/tmp 的临时副本并跑契约测试，正式库一个字节都不动 --------
if [ "$MODE" = "--drill" ]; then
    mkdir -p data/tmp
    TMP_DB="data/tmp/restore-drill-$(date +%Y%m%d-%H%M%S).db"
    cp "$DUMP" "$TMP_DB"
    echo "演练：把 $DUMP 恢复到临时副本 $TMP_DB（正式库未改动）"
    if "$PYTHON_BIN" scripts/contract_tests.py --restored --use-db "$TMP_DB"; then
        echo "演练通过：恢复出来的副本可用（可读、health、总览、语料审计、检索、空结果、错误码）"
        echo "副本保留在 $TMP_DB（确认后可自行删除；data/tmp/ 不入仓库）"
        exit 0
    fi
    echo "演练未通过：副本不可用，正式库未受影响；副本留在 $TMP_DB 供排查" >&2
    exit 1
fi

if [ "$MODE" != "--yes" ]; then
    echo "恢复会覆盖 data/xungen.db。确认后加 --yes 再执行（脚本会先自动备份当前库）；" >&2
    echo "只想演练不覆盖正式库，用 --drill。" >&2
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
one_query() {
    if [ -n "$CURL_BIN" ]; then
        "$CURL_BIN" -fsS "http://127.0.0.1:$PORT/api/surnames/%E6%9D%8E" >/dev/null
    else
        "$PYTHON_BIN" - "$PORT" <<'PYEOF'
import sys, urllib.request
with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/surnames/%E6%9D%8E", timeout=5) as response:
    assert response.status == 200
PYEOF
    fi
}
if check; then
    echo "恢复后自检：/api/health 正常"
    if one_query; then
        echo "恢复后自检：/api/surnames/李 返回 200（一条真实查询）"
    else
        echo "恢复后自检失败：健康检查过但查询不通，放回恢复前的备份" >&2
        [ -f "$SAFETY" ] && cp "$SAFETY" data/xungen.db
        exit 1
    fi
else
    echo "恢复后自检失败：把 $SAFETY 放回 data/xungen.db，并检查 logs/app.log" >&2
    [ -f "$SAFETY" ] && cp "$SAFETY" data/xungen.db
    exit 1
fi
