# 姓氏郡望与家族迁徙寻根系统

[![CI](https://github.com/Jerry-Ca/surname_app/actions/workflows/ci.yml/badge.svg)](https://github.com/Jerry-Ca/surname_app/actions/workflows/ci.yml)

**证据优先的姓氏研究工具**：用户输入姓氏后，可以看到最早书证、历史郡望、迁徙线索和语料审计，并展开每一条证据的出处、原文摘录与核对状态。系统不给出无法追溯的结论——没有证据时明确回答“当前资料不足以确认”。

- 课程课题：课题 12（最早书证 / 历史郡望 / 迁徙线索 / 语料审计），5 人小组
- 当前阶段：三天冲刺协作框架已就绪，等待 Day1 开工
- 期末定位：三天版本是正式版本的起点，保留数据库、证据编号、来源关系与审核记录

## 三天验收目标

| 阶段 | 当天结束时的验收标准 |
| --- | --- |
| Day1 | 输入「李」，前端通过 API 从数据库读到真实证据，证据可展开看到文献来源，项目可在本地启动 |
| Day2 | 不调用大模型时结构化查询已完整；已收录与未收录姓氏都有合理结果；数据库 ≥100 条可追踪证据 |
| Day3 | 校园网与手机网络可打开公网地址；证据可追溯；AI 回答带证据编号；模型关闭后结构化功能仍可用 |

## 五个人怎么分工

| 角色 | 主责目录 | 最终交付 |
| --- | --- | --- |
| A 产品与总集成 | `docs/` `.github/` | 需求文档、验收清单、演示脚本、可运行最终版本 |
| B 文献数据与管线 | `data/` | 100+ 证据、来源登记、导入文件、数据审计记录 |
| C 后端与数据库 | `backend/` `migrations/` | 数据库迁移、后端 API、导入脚本、备份脚本 |
| D 前端与交互 | `frontend/` | React 页面、组件、联调版本、交互验收 |
| E RAG、部署与测试 | `backend/rag/` `deploy/` | RAG 模块、部署脚本、公网地址、测试报告 |

每个人的任务编号（A-01 … E-06，共 30 个）在 [docs/collaboration/tasks.json](docs/collaboration/tasks.json)，按人分工的三天日程在 [docs/collaboration/sprint-plan.md](docs/collaboration/sprint-plan.md)。

当前名册：**B = @devinbro326**（已加入）、**C = @Jerry-Ca**（仓库负责人）、**E = @Dayevid**（邀请已发出，待接受）、A / D 待定。账号写在 [team.json](docs/collaboration/team.json)，改完重新生成 CODEOWNERS 即可。

## 快速开始

```bash
# 1) 后端（Python 3.12）
cd backend
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example ../.env          # 填 DATABASE_URL；没有模型 Key 也能启动（降级模式）
uvicorn app.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000/api/health 应返回 status=ok

# 2) 前端（另开一个终端）
cd frontend
npm install
npm run dev
# 打开 http://127.0.0.1:5173，/api 已代理到 8000

# 3) 数据校验（CI 同款门禁）
python scripts/validate_data.py --path data
```

一键启动：`bash scripts/dev.sh`（同时拉起后端与前端，需要 Git Bash）。
Windows PowerShell 用户请在两个终端分别执行 `uvicorn app.main:app --reload --port 8000`（在 `backend/` 下）
与 `npm run dev`（在 `frontend/` 下）；仓库里的 `setup_repo.ps1` 等 PowerShell 脚本不需要 bash。

## 协作入口

| 我需要… | 看这里 |
| --- | --- |
| 今天该做什么、卡片怎么流转 | [任务看板](https://github.com/users/Jerry-Ca/projects/1) · [task-board.md](docs/collaboration/task-board.md) |
| 日常怎么提交、怎么开 PR、冲突谁解 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 交给 AI 助手写代码的约束与七段式 Prompt | [AGENTS.md](AGENTS.md) |
| 仓库要开哪些保护规则、标签和看板怎么配 | [docs/collaboration/github-settings.md](docs/collaboration/github-settings.md) |
| 看板列、每日节奏、任务依赖 | [docs/collaboration/task-board.md](docs/collaboration/task-board.md) |
| 模块交接给谁、接收方怎么验收 | [docs/collaboration/handoff.md](docs/collaboration/handoff.md) |
| 需求范围（课题 12 硬性输出） | [docs/requirements.md](docs/requirements.md) |
| 验收步骤（含异常状态） | [docs/acceptance.md](docs/acceptance.md) |
| 字段命名与状态枚举 | [docs/data-dictionary.md](docs/data-dictionary.md) |
| 接口字段、错误码、空结果结构 | [docs/api-contract.md](docs/api-contract.md) |
| 数据从哪来、怎么清洗、怎么入库 | [docs/data-pipeline.md](docs/data-pipeline.md) |
| 服务器怎么部署、端口怎么开 | [docs/deployment.md](docs/deployment.md) |
| 演示怎么走 | [docs/demo-script.md](docs/demo-script.md) |
| Prompt 记录与迭代记录模板 | [docs/prompt-log.md](docs/prompt-log.md) |

## 目录结构

```
surname_app/
├─ frontend/          React + Vite 前端（D 主责）
├─ backend/           FastAPI 后端（C 主责；backend/rag 归 E）
├─ migrations/        Alembic 数据库迁移（C 主责）
├─ data/              raw 原始 / cleaned 清洗 / verified 已核对 / templates 模板（B 主责）
├─ scripts/           数据校验、导入、备份、GitHub 初始化脚本
├─ docs/              契约文档、协作规范、Prompt Log、测试报告
├─ deploy/            Nginx、systemd、部署说明（E 主责）
├─ .github/           Issue/PR 模板、CI 工作流、CODEOWNERS
├─ AGENTS.md          Agent 协作约束（含七条铁律）
└─ CONTRIBUTING.md    日常协作规范
```

## 开工前的状态清单

已经就绪（无需再操作）：CI 三个检查（`backend` / `frontend` / `data-check`）、`main` 分支保护、
22 个协作标签、3 个里程碑、30 张任务卡、Projects 看板（列 + 角色 + 冲刺日 + 30 张卡入板）。

还需要人工完成：

1. **协作者邀请**：B（@devinbro326）的 Write 邀请已发出，等他接受；A/D/E 定下来后同样邀请：
   `gh api -X PUT repos/Jerry-Ca/surname_app/collaborators/<用户名> -F permission=push`。
   **未接受邀请的账号不能被指派 issue**（GitHub 返回 422），也看不到看板，所以这一步不能拖。
2. **补齐名册**：把 A/D/E 的账号填进 [team.json](docs/collaboration/team.json)，然后
   `node scripts/gen_codeowners.mjs`（让 CODEOWNERS 指向真人）→
   `node scripts/seed_github.mjs --apply --reassign`（把任务卡指派给各自主责人）。
   未填账号的角色保持未指派，不会落到兜底账号上；兜底只用于 CODEOWNERS。
3. 看板还有两处只能在界面点：视图的 `Group by`（按人→角色、按日→冲刺日）与内置 Workflows 自动化，见
   [docs/collaboration/github-settings.md](docs/collaboration/github-settings.md) 第 5 节。
4. 准备服务器（大陆地域轻量应用服务器 + 公网 IP）与 DeepSeek API Key，只写入服务器环境变量。
5. 确认首批 8—10 个姓氏的可访问文献来源；B 先登记来源，再整理证据。

## 红线

**不得编造古籍、卷次、年代、原文、地点或迁徙事件。** 大模型只能整理和解释已检索出的证据；没有来源、没有卷次、没有原文的记录不得进入 `data/verified/`。完整七条约束见 [AGENTS.md](AGENTS.md)。