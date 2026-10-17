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

看板已创建：**<https://github.com/users/Jerry-Ca/projects/1>**
名称「姓氏郡望与家族迁徙寻根系统 · 三日冲刺看板」，关联本仓库。列、字段与流转规则见 [task-board.md](task-board.md)。

重建或同步（幂等，可随时重跑；新增任务卡后也用它把新卡加进看板）：

```bash
node scripts/setup_board.mjs             # 干跑：打印将创建的内容
node scripts/setup_board.mjs --apply     # 实际创建/补齐
```

脚本已经做好：列 = Status 字段的 7 个选项、`角色`（A—E）与 `冲刺日`（Day1—Day3）两个单选字段、
30 张任务卡入板并填好 Status=Backlog 与角色/冲刺日、三个视图（按人／按日／阻塞）。
需要 token 具备 `project` scope：`gh auth refresh -s project`。

**还剩两件必须在界面点一次的事**（Projects v2 没有对应 API）：

1. 视图分组：打开「按人」视图点 `Group by → 角色`，打开「按日」视图点 `Group by → 冲刺日`。API 的 view 配置只接受 `visibleFieldIds`，分组字段设不了。
2. 内置自动化：Project 右上角 `⋯ → Workflows`，打开这四条：
   - `Auto-add to project` → 过滤填 `is:issue repo:Jerry-Ca/surname_app`（**不要漏这条**：交接卡、缺陷卡默认不会进看板，只能手工加）
   - `Item added to project → 状态置 Backlog`
   - `Item closed → 状态置 Done`
   - `Pull request linked to issue → 状态置 Review`

> 脚本只把 `tasks.json` 里的 30 张任务卡加进看板。新增的交接卡（`[HANDOFF]`）与缺陷卡要靠上面的 Auto-add，或手工 `Add item`。
> 建板当天就出现了两张不在板上的交接卡（#38 C→D、#39 C→E），已手工加入 `Verify` 列；
> 按 [handoff.md](handoff.md) 第 1 节，接收方必须填完「接收方验收结果」才能关闭这两张卡。

### 5.1 让五个人都能看到并更新看板

看板目前是**私密**的，只有仓库协作者能访问。开工前必须把 5 人加为仓库协作者（`Write` 权限），否则他们既推不了分支，也看不到看板：

```bash
gh api -X PUT repos/Jerry-Ca/surname_app/collaborators/<对方用户名> -F permission=push
# 或者界面：Settings → Collaborators → Add people（权限选 Write）
```

当前状态：B（`@devinbro326`）的邀请已发出、**等待对方接受**；A/D/E 账号待定。

**未接受邀请的账号无法被指派 issue**——`seed_github.mjs` 会返回 422，因此脚本改成先读
`/collaborators` 与 `/invitations`：不在已接受列表里的账号一律不指派，并在输出里注明原因，
对方接受邀请后再跑一次 `node scripts/seed_github.mjs --apply --reassign` 即可补上。

加完协作者后有个额外好处：评审请求能真正流转，PR 不再需要 `--admin` 绕过（见第 6 节）。

## 6. CODEOWNERS

`.github/CODEOWNERS` 由脚本从 [team.json](team.json) 生成，不要手改：

```bash
node scripts/gen_codeowners.mjs
```

在团队成员的 GitHub 账号填入 `team.json` 之前，CODEOWNERS 的所有规则都指向仓库负责人（`fallback_handle`），此时目录归属是“名义上正确、实际上无人交叉评审”。注意**兜底只作用于 CODEOWNERS**：issue 指派不使用兜底，未填账号的角色其任务卡保持未指派（否则会把 B/D/E 的卡挂到并非该角色的人名下）。这带来一个必须知道的副作用：

- PR 作者**不能给自己做 code owner 评审**。在 5 个账号填齐之前，如果 PR 也由仓库负责人提交，`Require review from Code Owners` 就没人能满足；
- 本仓库 `enforce_admins=false`，因此仓库管理员可以绕过这条规则合并（这也是三天冲刺里唯一需要的例外通道）；
- 交叉评审真正生效的时间点，是**填齐 5 个 GitHub 账号并重新生成 CODEOWNERS 之后**。附录二要求收集每个人的 Git 账号，原因就在这里。

**实测记录（2026-10-17，PR #31）**：账号未填齐时开 PR，三个必需检查 `backend` / `frontend` / `data-check` 都正常触发并通过，但 GitHub **不把评审请求发给作者本人**（`reviewRequests` 为空），PR 停在 `BLOCKED`。这不是配置错误，是本节的预期行为。

三天冲刺期间的例外通道（只有 A 用，且必须在 PR 里写清理由）：

```bash
gh pr merge <编号> --squash --delete-branch --admin   # 管理员绕过评审要求，CI 仍然必须全绿
```

`--admin` 只绕过评审要求，**不会**绕过 CI 必需检查；不要为了合并方便去关掉分支保护，那等于放弃整个数据门禁。

填好账号后的两步（顺序不能颠倒，先让 CODEOWNERS 指向真实的人，再让指派回填到已建的任务卡）：

```bash
# 1) 编辑 docs/collaboration/team.json，把 5 个人的 github 字段填上（不带 @）
node scripts/gen_codeowners.mjs            # 重新生成 CODEOWNERS
git add .github/CODEOWNERS docs/collaboration/team.json
git commit -m "chore(A-05): CODEOWNERS 指向真实团队账号" && git push origin main

# 2) 把 30 张任务卡的指派从仓库负责人改回各自主责人
node scripts/seed_github.mjs --apply --reassign
```

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