#!/bin/sh
# 部署到共享服务器（任务 C-07 / C-14 的服务器侧辅助脚本）。
#
# 用法（在 xungen12/ 下执行）：
#   sh scripts/deploy_to_server.sh ubuntu@81.71.14.93 18888                 # 上传 + 前置自检 + 建库 + 契约测试
#   sh scripts/deploy_to_server.sh ubuntu@81.71.14.93 18888 --start         # 上面全部 + 启动服务
#   sh scripts/deploy_to_server.sh ubuntu@81.71.14.93 18888 --start --static /path/to/dist
#
# 前置条件（缺一个都会在这里明确报错并停下，不做任何"绕过去"的动作）：
#   1. 本机能免密登录目标机，二选一：
#      - 专用部署密钥（推荐）：SSH_KEY=~/.ssh/id_ed25519_xungen12_deploy sh scripts/deploy_to_server.sh ...
#      - 或把密钥交给 ssh-agent：eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519
#      脚本不会尝试破解、也不会索取或保存任何口令。
#   2. 服务器上目标目录可写（默认 /home/ubuntu/guji-jiaocuo/xungen12，可用 REMOTE_DIR 覆盖）。
#   3. 服务器上 python3 版本 >= 3.8（runtime_check.sh 会打印实际版本并断言）。
#
# 传的是 **git 里已提交的内容**（git archive），因此不会把本地的 data/xungen.db、logs/、run/、
# backups/、__pycache__ 带上服务器，也不会覆盖服务器上已有的数据库。
set -eu

TARGET="${1:-}"
PORT="${2:-18888}"
SHIFT_COUNT=2
[ -z "$TARGET" ] && { echo "用法：sh scripts/deploy_to_server.sh <user@host> [端口] [--start] [--static <目录>]" >&2; exit 2; }
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/guji-jiaocuo/xungen12}"
START_SERVICE=""
STATIC_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --start) START_SERVICE="--start" ;;
        --static) shift; STATIC_DIR="${1:-}" ;;
    esac
    shift
done

cd "$(dirname "$0")/.."          # 项目根 = xungen12/
command -v ssh >/dev/null 2>&1 || { echo "没有 ssh 客户端，无法部署" >&2; exit 2; }
SSH_KEY="${SSH_KEY:-}"
if [ -n "$SSH_KEY" ]; then
    [ -f "$SSH_KEY" ] || { echo "指定的密钥不存在：$SSH_KEY" >&2; exit 2; }
    remote() { ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 "$TARGET" "$@"; }
else
    remote() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$TARGET" "$@"; }
fi

echo "== 1/5 检查免密登录与目录可写 =="
if ! remote "echo connected" >/dev/null 2>&1; then
    cat >&2 <<'MSG'
无法免密登录目标机。请先在本机解锁密钥（只需做一次，passphrase 由你本人输入，不要发给任何人）：

    eval "$(ssh-agent -s)"          # Git Bash / Linux
    ssh-add ~/.ssh/id_ed25519       # 提示 Enter passphrase 时输入你自己的口令

然后再跑本脚本。若仍失败，说明公钥还没加到服务器的 authorized_keys。
MSG
    echo "（也可以指定专用密钥：SSH_KEY=~/.ssh/id_ed25519_xungen12_deploy ...）" >&2
    exit 3
fi
remote "mkdir -p '$REMOTE_DIR' && test -w '$REMOTE_DIR'" || {
    echo "目标目录不可写：$REMOTE_DIR —— 按执行清单的停线规则，请 A 联系服务器所有者" >&2
    exit 4
}
echo "  已连接，目标目录可写：$REMOTE_DIR"

echo "== 2/5 打包上传（只传 git 已提交的内容）=="
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git archive --format=tar HEAD:xungen12 | gzip -9 | remote "tar xzf - -C '$REMOTE_DIR'"
    echo "  已用 git archive 上传（不含本地数据库与日志）"
else
    tar czf - --exclude='./data/xungen.db*' --exclude='./data/tmp' --exclude='./logs' \
        --exclude='./run' --exclude='./backups' --exclude='__pycache__' --exclude='./static' . \
        | remote "tar xzf - -C '$REMOTE_DIR'"
    echo "  已用 tar 上传（排除运行产物）"
fi

if [ -n "$STATIC_DIR" ]; then
    echo "== 2b/5 上传前端构建产物到 static/ =="
    [ -d "$STATIC_DIR" ] || { echo "静态目录不存在：$STATIC_DIR" >&2; exit 2; }
    tar czf - -C "$STATIC_DIR" . | remote "mkdir -p '$REMOTE_DIR/static' && tar xzf - -C '$REMOTE_DIR/static'"
    echo "  已上传 $STATIC_DIR → $REMOTE_DIR/static"
fi

echo "== 3/5 服务器侧前置自检（运行时、目录、端口、代码可编译可导入）=="
remote "cd '$REMOTE_DIR' && sh scripts/runtime_check.sh $PORT" || {
    echo "前置自检未通过：按上面的输出停线（不要 pip 装包、不要 sudo）" >&2
    exit 5
}

echo "== 4/5 建库 + 契约测试（用临时库，不碰正式库）=="
remote "cd '$REMOTE_DIR' && python3 scripts/init_db.py && python3 scripts/contract_tests.py --quick"

if [ "$START_SERVICE" = "--start" ]; then
    echo "== 5/5 启动服务 =="
    remote "cd '$REMOTE_DIR' && PORT=$PORT sh scripts/start.sh"
    sleep 2
    echo "本机自检："
    remote "curl -fsS http://127.0.0.1:$PORT/api/health || python3 -c \"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:$PORT/api/health').read().decode())\""
    echo
    echo "站外验证（从你这台机器跑）："
    echo "  curl -s http://${TARGET#*@}:$PORT/api/health"
    echo "  http://${TARGET#*@}:$PORT/            ← 网页（需要 static/ 里有 D 的构建产物）"
else
    echo "== 5/5 跳过启动（要启动请加 --start）=="
    echo "  服务器上手动启动：ssh $TARGET 'cd $REMOTE_DIR && PORT=$PORT sh scripts/start.sh'"
fi

echo
echo "完成。剩余人工步骤：把网页地址 http://${TARGET#*@}:$PORT/ 交给 D 验证；"
echo "站点外连不上而本机自检正常，请服务器所有者放行该端口入站。"
[ -n "$STATIC_DIR" ] || echo "提示：还未上传 frontend 构建产物，/ 会返回 404（/api/* 正常）。"