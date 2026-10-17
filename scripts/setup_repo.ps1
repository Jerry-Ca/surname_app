# 一次性配置 GitHub 仓库（与 scripts/setup_repo.sh 等价，供 Windows / PowerShell 使用）
#
#   powershell -ExecutionPolicy Bypass -File scripts/setup_repo.ps1          干跑，只打印
#   powershell -ExecutionPolicy Bypass -File scripts/setup_repo.ps1 -Apply   实际执行
#
# 说明：本文件的功能性字符串保持 ASCII，只让注释用中文——
#       Windows PowerShell 5.1 读取无 BOM 的 .ps1 时按本地代码页解码，中文注释可能显示乱码但不影响执行；
#       真正需要输出中文的部分（标签、里程碑、issue 正文）由 node scripts/seed_github.mjs 负责。
#
# 顺序要求：先确认 .github/workflows/ci.yml 已在远程并跑出 backend / frontend / data-check
#           三个检查，再执行本脚本；否则分支保护的必需检查指向不存在的名字，PR 会一直 pending。

[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Repo = "Jerry-Ca/surname_app"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Invoke-Step {
    param([string]$Description, [scriptblock]$Action)
    if ($Apply) {
        Write-Host "+ $Description"
        & $Action
    }
    else {
        Write-Host "[DRY-RUN] $Description"
    }
}

Write-Host ""
Write-Host "Repository: $Repo"
Write-Host "Mode: $(if ($Apply) { 'APPLY' } else { 'DRY-RUN (use -Apply to execute)' })"
Write-Host ""

Write-Host "== 1. merge strategy: squash only, delete branch after merge =="
Invoke-Step "gh api --method PATCH repos/$Repo  (allow_squash_merge=true, others=false)" {
    gh api --method PATCH "repos/$Repo" `
        -F allow_squash_merge=true `
        -F allow_merge_commit=false `
        -F allow_rebase_merge=false `
        -F delete_branch_on_merge=true `
        -F allow_auto_merge=true | Out-Null
}

Write-Host ""
Write-Host "== 2. main branch protection: PR + 1 approval + code owners + required checks =="
$protection = @'
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
'@
Invoke-Step "gh api --method PUT repos/$Repo/branches/main/protection  (contexts: backend, frontend, data-check)" {
    $protection | gh api --method PUT "repos/$Repo/branches/main/protection" --input -
}

Write-Host ""
Write-Host "== 3. labels / milestones / 30 task issues (idempotent) =="
Invoke-Step "node scripts/seed_github.mjs --apply" {
    node scripts/seed_github.mjs --apply
}

Write-Host ""
Write-Host "== 4. regenerate CODEOWNERS from team.json =="
Invoke-Step "node scripts/gen_codeowners.mjs" {
    node scripts/gen_codeowners.mjs
}

Write-Host ""
if ($Apply) {
    Write-Host "Done. Verify in the browser:"
}
else {
    Write-Host "Dry run only. Re-run with -Apply to change the repository. Then verify:"
}
Write-Host "  1) Settings > Branches: main rule lists backend / frontend / data-check as required"
Write-Host "  2) Settings > Actions > General: Workflow permissions = Read repository contents"
Write-Host "  3) Projects > New project > Board: columns and fields per docs/collaboration/task-board.md"
Write-Host "  4) Fill 5 GitHub accounts into docs/collaboration/team.json, then re-run:"
Write-Host "     node scripts/gen_codeowners.mjs"
Write-Host "     node scripts/seed_github.mjs --apply --reassign   (fix issue assignees)"
Write-Host "  5) After the server is ready, follow docs/deployment.md (open 80/443/22 only)"
Write-Host ""
Write-Host "Note: creating a Projects board additionally needs: gh auth refresh -s project"