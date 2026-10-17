# 协作规范（日常操作只看这一份）

项目：姓氏郡望与家族迁徙寻根系统 · 5 人 / 3 天冲刺 + 期末持续建设
配套文档：[AGENTS.md](AGENTS.md)（Agent 约束）· [docs/collaboration/github-settings.md](docs/collaboration/github-settings.md)（仓库设置）· [docs/collaboration/task-board.md](docs/collaboration/task-board.md)（看板与节奏）

## 1. 五个人的目录边界

| 角色 | 主责目录 | 一句话 |
| --- | --- | --- |
| A 产品与总集成 | `docs/`、`.github/`、`README.md` | 决定范围、检查接口、合并成果、验收演示 |
| B 文献数据与管线 | `data/` | 把真实文献整理成可核验记录 |
| C 后端与数据库 | `backend/`、`migrations/`、`scripts/import_data.py` | 把数据做成稳定可调用的服务 |
| D 前端与交互 | `frontend/` | 把 API 结果做成可演示的网页 |
| E RAG、部署与测试 | `backend/rag/`、`backend/search/`、`deploy/` | 证据问答 + 国内网络可访问 |

只改自己负责的目录。需要别人目录里的改动时，**开 issue 让对方改**，不要顺手改掉。
目录边界与铁律的完整版见 [AGENTS.md](AGENTS.md)。

## 2. 分支模型

`main` 始终可演示、可部署，任何人不直接 push `main`。

| 分支 | 用途 | 命名示例 |
| --- | --- | --- |
| `main` | 受保护主干，只接受 PR 合并 | — |
| `feat/*` | 功能开发 | `feat/c-c04-surname-api` |
| `data/*` | 数据整理与核验 | `data/b-b03-verified-batch1` |
| `docs/*` | 文档与契约 | `docs/a-a04-api-contract` |
| `fix/*` | 缺陷修复 | `fix/d-d03-broken-source-link` |
| `deploy/*` | 部署与运维 | `deploy/e-e05-nginx-proxy` |
| `chore/*` | CI、依赖、脚手架 | `chore/a-ci-data-check` |

命名规则：`<类型>/<角色小写>-<任务编号小写>-<简短描述>`，任务编号取自 [docs/collaboration/tasks.json](docs/collaboration/tasks.json)。

```bash
# 开工
git switch main && git pull --ff-only
git switch -c feat/c-c04-surname-api

# 收工（推送前先同步主干，减少整合时的冲突）
git fetch origin && git rebase origin/main
git push -u origin feat/c-c04-surname-api
```

分支生命周期不超过 1 天：当天做完的部分当天合并进 `main`，没做完的部分新开分支次日继续，不要让一个分支挂过夜。

## 3. 提交信息

格式：`<type>(<任务编号>): <简述>`

```
feat(C-04): 实现姓氏总览与最早书证接口
fix(D-03): 来源链接失效时保留书名卷次并标记待复查
data(B-03): 首批 15 条已核对证据，含卷次与原文摘录
docs(A-04): 冻结 v1 接口契约，补充错误码与空结果结构
deploy(E-05): 增加 nginx 反代与 systemd 单元
```

`type` 取值：`feat` / `fix` / `docs` / `data` / `test` / `deploy` / `chore` / `refactor`。

一次提交只做一件事。数据库迁移与导入脚本的提交必须在信息中写明“已实测”或“未实测”。

## 4. PR 流程

1. 用仓库默认模板建 PR，标题与提交信息同格式（例：`feat(C-04): 姓氏总览接口`）。
2. 关联 issue：正文写 `Closes #<issue号>`。
3. 填完模板里的验证结果，CI 三个作业（backend / frontend / data-check）必须全绿。
4. 评审配对：
   - C 的 PR → E 或 D 评审（D 确认字段够用，E 确认可部署）
   - D 的 PR → C 或 A 评审
   - B 的 PR → A 评审（数据真实性），涉及争议数据加 `data-review` 标签
   - E 的 PR → C 评审（数据库与进程）
   - A 的 PR → 对应模块负责人评审
5. 合并方式统一 **Squash and merge**，合并后删除分支。
6. 合并权归 A（或 A 授权者）。A 不在时，主责人可自行合并自己模块的 PR，但必须在整合记录里说明。

## 5. 每天至少一次整合

| 时间 | 动作 |
| --- | --- |
| 每天 21:00 | 整合检查点：当天分支合并进 `main`，A 逐条过看板 |
| 每天 22:00 前 | 在看板更新状态；未完成项写成次日 issue 并指定负责人 |
| Day3 12:00 | 冻结 `main`，只接受 P0 修复；打标签 `v1.0.0` |

整合时必答三问：**接口字段有没有变？谁的交付物还没接上？明天第一件事是什么？**
记录写在 [docs/collaboration/handoff.md](docs/collaboration/handoff.md) 的整合记录区。

## 6. 冲突处理

- 冲突出现在谁的目录，谁负责解，其他人不代劳。
- 跨目录冲突（如契约字段名不一致）由 A 裁决，先改 `docs/api-contract.md` 再改代码。
- 禁止 `git push --force` 到 `main`；禁止 rebase 别人已推送的分支。
- 数据文件的冲突不要靠编辑器手改：重新跑一遍导出脚本生成 CSV，再提交。
- 发现别人的 PR 里混进了你的文件，或你的 PR 里混进了别人的文件：**不要合并**，按第 9 节重建分支。

## 7. 同一个工作目录有多人或多 Agent 时（必读）

几个 AI 会话（或几个人）共用同一个本地目录并行改代码时，**禁止用 `git add -A` / `git add .`**：
它们会把同伴尚未提交的改动一起卷进你的提交，PR 里出现别人的文件；一旦合并，还可能把对方正在写的版本顶掉。
2026-10-17 真实发生过一次：一个「加看板脚本」的提交卷进了 8 个后端文件。

规矩：

```bash
git status                                   # 先看清工作区里有什么，再决定提交什么
git add backend/app/api/surnames.py backend/tests/test_queries.py   # 只加本任务允许修改的文件
git show --stat HEAD                         # 提交后自查：文件清单应与任务卡的「允许修改的文件范围」一致
```

- 更稳妥的做法是每人一个 clone，或用 `git worktree` 物理隔离：
  `git worktree add ../surname_app-C -b feat/c-c04`。
- 提交前发现工作区里有别人模块的改动，**不要提交、也不要还原**，直接放着继续做自己的事。
- PR 里混进别人的文件时，重建分支：`git switch -c <新分支> main` →
  `git checkout <那个提交> -- <自己的文件>` → force-push 更新同一个 PR（见第 2 节分支命名规则）。

## 8. 绝对不能提交的东西

- 任何 API Key、服务器密码、数据库密码（只放服务器环境变量与本地 `.env`）。
- 抓取平台的受限全文内容；只提交短摘录 + 链接 + 登记表。
- `data/raw/` 下的大体积原始文件（已在 `.gitignore` 中忽略）。
- 编造的书名、卷次、年代、原文、地点、迁徙事件。**这一条是红线。**

## 9. 出问题时的顺序

先看 CI 日志 → 再看 [docs/acceptance.md](docs/acceptance.md) 对应条目 → 在自己模块内定位 → 跨模块问题贴看板并 @ 对方 → 仍无法解决再找 A 裁决。
不要在群里口头交接，所有交接都要落到 issue 评论或整合记录里。