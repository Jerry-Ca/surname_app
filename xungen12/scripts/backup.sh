#!/bin/sh
# 备份数据库（执行清单 §二 / §三.10）：cp data/xungen.db backups/xungen-YYYYmmdd-HHMM.db
# 用法：sh scripts/backup.sh [标签]        标签会加在文件名末尾，如 day3
set -eu
cd "$(dirname "$0")/.."
LABEL="${1:-}"
STAMP="$(date +%Y%m%d-%H%M)"
mkdir -p backups
if [ ! -f data/xungen.db ]; then
    echo "没有 data/xungen.db，先运行 python3 scripts/init_db.py" >&2
    exit 1
fi
SUFFIX=""
[ -n "$LABEL" ] && SUFFIX="-$LABEL"
TARGET="backups/xungen-$STAMP$SUFFIX.db"
cp data/xungen.db "$TARGET"
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$TARGET" > "$TARGET.sha256"
    echo "校验和：$(cut -d' ' -f1 "$TARGET.sha256")"
fi
echo "备份完成：$TARGET（$(du -h "$TARGET" | cut -f1)）"
echo "现有备份："
ls -lh backups | tail -n +2
