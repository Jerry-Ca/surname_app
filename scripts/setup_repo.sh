#!/usr/bin/env bash
# 一次性配置 GitHub 仓库：合并策略 + main 分支保护 + 标签/里程碑/任务卡。
#
#   bash scripts/setup_repo.sh             只打印将要做的事（干跑）
#   bash scripts/setup_repo.sh --apply     实际修改仓库设置
#
# 前置：gh auth status 已登录；如需 Project 看板，先 gh auth refresh -s project。
set -euo pipefail

REPO="Jerry-Ca/surname_app"
APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

run() {
  if $APPLY; then
    echo "+ $*"
    "$@"
  else
    echo "[干跑] $*"
  fi
}

echo "== 1. 合并策略：只允许 squash，合并后自动删分支 =="
run gh api -X PATCH "repos/$REPO" \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true \
  -F allow_auto_merge=true

echo
echo "== 2. main 分支保护：PR + 1 名评审 + Code Owners + CI 必需检查 =="
if $APPLY; then
  gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["backend", "frontend", "data-check"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
else
  echo "[干跑] gh api -X PUT repos/$REPO/branches/main/protection（规则见 docs/collaboration/github-settings.md 第 2 节）"
fi

echo
echo "== 3. 标签 / 里程碑 / 30 张任务卡 =="
run node scripts/seed_github.mjs --apply

echo
echo "== 4. CODEOWNERS（从 team.json 重新生成） =="
run node scripts/gen_codeowners.mjs

echo
if $APPLY; then
  echo "完成。接下来人工确认："
else
  echo "以上为干跑结果。加 --apply 才会真正执行。确认后人工检查："
fi
cat <<'NEXT'
  1) Settings → Branches：main 规则里应出现 backend / frontend / data-check 三个必需检查
     （三个检查名必须与 .github/workflows/ci.yml 的 job 名一致，否则 PR 会一直 pending）
  2) Settings → Actions → General：Workflow permissions 设为 Read repository contents
  3) Projects → New project → Board：列与字段按 docs/collaboration/task-board.md 第 1、2 节配置
  4) 把 5 名成员的 GitHub 账号填进 docs/collaboration/team.json 后重新运行 gen_codeowners.mjs
  5) 服务器就绪后按 docs/deployment.md 开通 80/443/22，数据库不暴露公网
NEXT