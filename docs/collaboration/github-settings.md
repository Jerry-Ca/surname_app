# 仓库设置（一次性配置，Day1 上午 30 分钟内做完）

这些设置无法用仓库里的文件表达，必须在 GitHub 网页或 CLI 上操作一次。做完后整个协作框架才开始生效。

前置：确认已登录 `gh auth status`；如需创建 Project 看板，先补授权 `gh auth refresh -s project`。

## 0. 如果推送被拒：workflow scope（**第一件要做的事**）

`.github/workflows/ci.yml` 需要 token 具备 `workflow` scope 才能创建或更新。用 `gh` 登录的默认 token 只有 `repo` / `read:org` / `gist`，直接推送会看到：

```
! [remote rejected] main -> main (refusing to allow an OAuth App to create or update
  workflow `.github/workflows/ci.yml` without `workflow` scope)
```

由于 CI 文件还没进仓库，**第 2 节的必需检查（backend / frontend / data-check）在 GitHub 上不存在**，
这一步没做完就打开分支保护，所有 PR 会一直卡在 pending。顺序必须是先 CI、后保护：

```bash
gh auth refresh -s workflow                     # 浏览器里点一次授权，约 15 秒
git add .github/workflows/ci.yml
git commit -m "chore(A-05): 启用 CI 工作流"
git push origin main
gh run list --limit 3                           # 确认三个作业已开始运行
```

CI 跑过一次并出现 `backend` / `frontend` / `data-check` 三个检查名之后，再做下面第 2 节的分支保护。

> **Windows 用户注意**：仓库里的 `*.sh` 需要 Git Bash，PowerShell 里直接敲 `bash` 会报
> `无法将"bash"项识别为 cmdlet`。上面这四条、以及下面的 `scripts/setup_repo.ps1`，
> 都不依赖 bash，在 PowerShell 里直接可跑。只有 `scripts/dev.sh` 需要 Git Bash。

## 1. 合并策略（只允许 squash，合并后自动删分支）

```bash
gh api -X PATCH repos/Jerry-Ca/surname_app \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true \
  -F allow_auto_merge=true \
  -F description="证据优先的姓氏郡望与家族迁徙寻根系统：最早书证、郡望、迁徙线索与语料审计，每条结论都可追溯到来源。"
```

也可以直接用脚本：`bash scripts/setup_repo.sh --apply`（同时设置下方 2、3 两项）；
Windows PowerShell 用等价版本 `powershell -ExecutionPolicy Bypass -File scripts/setup_repo.ps1 -Apply`。

> 执行顺序提醒：先完成第 0 节（CI 进仓库），再执行 `setup_repo.sh --apply`，
> 否则脚本设置的三项必需检查会指向不存在的检查名，PR 全部卡住。

## 2. main 分支保护（最重要的一步）

需要的规则：

| 规则 | 值 | 为什么 |
| --- | --- | --- |
| Require a pull request before merging | 开 | 任何人不直接 push 主干 |
| Required approvals | 1 | 交叉评审，避免自己合自己的错 |
| Require review from Code Owners | 开 | 目录主责人必须点头 |
| Dismiss stale pull request approvals | 开 | 评审后又有新提交需重新确认 |
| Require status checks to pass | `backend`、`frontend`、`data-check` | CI 门禁，含数据真实性校验 |
| Require branches to be up to date | 开 | 防止“本地绿、合并后红” |
| Require conversation resolution | 开 | 评审意见必须落地 |
| Do not allow bypassing | 建议开（A 可保留 bypass 权限） | 三天冲刺期间允许 A 在 P0 时破例 |
| Allow force pushes / deletions | 全关 | 保护历史 |

CLI 方式（要求 status check 名与本仓库 `.github/workflows/ci.yml` 中的 job 名一致）：

```bash
gh api -X PUT repos/Jerry-Ca/surname_app/branches/main/protection \
  --input - <<'JSON'
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
```

> 注意：`contexts` 里的名字必须与 CI job 名完全一致。第一次推送后到 Actions 页面确认出现 `backend`、`frontend`、`data-check` 三个检查；如果名字不同，改 CI 的 job 名或这里的 contexts，不要两边各写一套。

## 3. Actions 权限

Settings → Actions → General：

- Actions permissions：**Allow all actions and reusable workflows**（CI 用到 `actions/setup-python`、`actions/setup-node`）。
- Workflow permissions：**Read repository contents**（CI 不需要写权限）。若将来要自动部署，再单独给对应 workflow 授权，不用仓库级写权限。
- 本项目 CI 不调用任何外部模型或数据平台，**不需要在仓库里放任何 Secret**。需要 Key 的测试一律用 mock（见 `docs/test-report.md` 的回归说明）。

## 4. 标签 / 里程碑 / 任务卡（一次性创建）

```bash
node scripts/seed_github.mjs            # 干跑：只打印将创建的内容，不做任何改动
node scripts/seed_github.mjs --apply    # 实际创建 22 个标签、3 个里程碑、30 张任务卡
```

生成内容是幂等的：已存在的标签会更新颜色与描述，已存在的里程碑和 issue 会跳过（按标题匹配）。

## 5. 项目看板（Projects v2）

看板的列、字段与流转规则见 [task-board.md](task-board.md)。创建步骤：

1. GitHub 仓库页 → Projects → New project → 选 **Board**。
2. 列（Columns）改为：`Backlog` / `Ready` / `In progress` / `Review` / `Blocked` / `Verify` / `Done`。
3. 自定义字段（Custom fields）：
   - `角色`：Single select，选项 `A` `B` `C` `D` `E`
   - `冲刺日`：Single select，选项 `Day1` `Day2` `Day3`
4. 自动化（Workflows）：`Item closed` → 状态置 `Done`；`Item added to project` → 状态置 `Backlog`；`Pull request linked to issue` → 状态置 `Review`。
5. 建议保存三个视图：**按人**（按 `角色` 分组）、**按日**（按 `冲刺日` 分组）、**阻塞**（过滤 `label:blocked`）。

## 6. CODEOWNERS

`.github/CODEOWNERS` 由脚本从 [team.json](team.json) 生成，不要手改：

```bash
node scripts/gen_codeowners.mjs
```

在团队成员的 GitHub 账号填入 `team.json` 之前，CODEOWNERS 会把评审请求统一指向仓库负责人（`fallback_handle`），保证分支保护里的 “Require review from Code Owners” 不会把 PR 卡死。

## 7. 仓库基础信息（可选）

```bash
gh repo edit Jerry-Ca/surname_app \
  --add-topic surname,chinese-history,genealogy,fastapi,react,rag,postgresql \
  --enable-issues --enable-discussions=false
```

## 8. 三天期间不建议开的功能

- 不要在 Day1–Day3 打开 required deployments 或环境审批，会拖慢合并。
- 不要为五个人各建长期分支（`dev-a`、`dev-b` 之类）。方案里“五个分支或任务目录”已经用**目录 + CODEOWNERS + 短分支**实现，长期分支在三天里只会制造冲突，这一点在 [CONTRIBUTING.md](../../CONTRIBUTING.md) 第 2 节已说明。
- 不要在 CI 里跑真实抓取或真实模型调用，网络抖动会让门禁失去意义。