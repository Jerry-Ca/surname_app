# backend/ — FastAPI 后端

主责：**C**（`backend/app/`、`migrations/`）。`backend/rag/` 主责是 **E**；搜索服务在 `app/services/search.py`，归 C（E-01 在其上做排序）。
接口字段的唯一依据是 [../docs/api-contract.md](../docs/api-contract.md)；表结构依据是 [../docs/data-dictionary.md](../docs/data-dictionary.md)。

## 运行

```bash
cd backend
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example ../.env                        # 填 DATABASE_URL；没填也能启动（降级模式）
uvicorn app.main:app --reload --port 8000
```

- 健康检查：<http://127.0.0.1:8000/api/health>
- 交互式文档：<http://127.0.0.1:8000/docs>
- 测试与静态检查：`pytest -q` / `ruff check .`

## 数据库迁移

表结构只能通过 `migrations/` 下的 Alembic 迁移创建与修改（不用 `create_all`）。命令都在 `backend/` 下执行：

```bash
alembic upgrade head      # 空库一次建齐（本地 SQLite 与服务器 PostgreSQL 相同命令）
alembic current           # 当前版本，与 /api/health 的 database.migration_revision 同源
alembic downgrade -1      # 回滚一步
alembic check             # 模型与迁移是否一致（改模型后必须没有待生成操作）
```

连接串来自环境变量 `DATABASE_URL`（见 `app/config.py`），不写在 `alembic.ini` 里。
`alembic.ini` 保持纯 ASCII：Python 的 configparser 按系统 locale 读它，中文注释会让 Windows（GBK）用户报 `UnicodeDecodeError`。

## 当前实现状态

| 部分 | 状态 |
| --- | --- |
| `/api/health` | 可用：真实探测数据库，模型/向量缺失时报 `degraded` |
| `/api/surnames/*` 五个查询接口 | 已接入数据库（C-04）：按契约第 4—7 节返回真实证据；未收录返回 200 + 空结构 + coverage 说明；`pending` 不外发、`retracted` 可见但不作结论 |
| `/api/surnames/{name}/corpus-checks` | 已接入 `corpus_searches`；**该接口尚未写进 `docs/api-contract.md`**，形状沿用 Day1 桩实现，需 A 补文档 |
| `POST /api/ask` | 返回 `degraded_no_model`，等 E-03/E-04 接入检索与校验 |
| `POST /api/admin/import` | 已实现（C-03）：库内校验 + 事务写入 + `ingestion_jobs` 审计；`/api/admin/reindex` 仍 501（E-01） |
| `backend/rag/*` | 只有接口签名与提示词骨架，实现归 E |
| `app/services/search.py` | 已实现（C-05）：姓氏标准化、别名匹配、精确匹配与全文检索；E-01 在此基础上做排序重排与向量补充 |
| `app/models/*` | 已实现（C-02）：13 张表 + 外键 + 状态校验 + 索引，由 `0001_initial` 迁移创建 |

查询接口的可见性规则（写死在 `app/services/queries.py`，与数据字典第 7 节一致）：

- `pending` 不返回给前端，只在 `coverage.pending_count` 与 `data_quality.caveats` 里计数提示；
- `retracted` 返回但排除在最早书证排序之外（列在 `sort_basis.excluded`）；
- 争议记录（`disputed` / `dispute_group`）全部返回，不做取舍；
- 未收录姓氏返回 **200 + 空结构 + coverage**，不是 404；
- `coverage.status` 按**可对外发布**的记录判定：只有 `pending` 时返回 `not_in_corpus`，并在 `note` 里说明“已查到 N 条但未通过核验”，避免前端拿到「已收录 + 空列表」。

## 导入侧的校验顺序（越早发现的错越省事）

1. 路径策略：只允许 `data/verified/`、`data/source_register.csv`、`data/corpus_searches.csv`（大小写不敏感）
2. 表头：缺必需列、重复列名 → **一条文件级错误**（`row=0`），不逐行轰炸
3. 列长度：按 `models/` 的 `String(n)` 上限校验超长值（SQLite 不强制、PostgreSQL 会拒，必须在导入侧拦住）
4. 逐行业务规则：枚举、编号、年份区间、外键存在性、重复证据、占位符
5. 写库：一个事务整体成功或整体不写入；`job_id` 先占号（撞号自动换号重试），`ingestion_jobs` 记录 `accepted/rejected/rolled_back`，`accepted + rejected == total` 恒成立

## 边界（违反会被打回）

- 只由 `app/services/` 访问数据库；路由层不直接写 SQL，E 的 `backend/rag/` 通过搜索服务拿证据。
- 不引入 `Base.metadata.create_all()`：表结构必须走 `migrations/`（AGENTS.md 铁律 5）。
- 不在代码或测试里调用真实 DeepSeek / Embedding：CI 必须离线可跑，真实调用只在服务器手工执行。
- 密钥只从环境变量读取（见 `app/config.py`），不写默认值、不写日志。
- 返回体字段一律 snake_case，且与 `api-contract.md` 一致；新增字段先改契约。

## 目录

```
app/
├─ main.py        FastAPI 应用装配
├─ config.py      环境变量配置（唯一配置入口）
├─ errors.py      统一错误结构（契约 1.2 节）
├─ timeutil.py    朴素 UTC ↔ ISO 8601 字符串（契约第 1 节）
├─ api/           路由：health / surnames / ask / admin
├─ db/            连接、会话、健康探测与 Base（base.py）
├─ models/        ORM 模型（C-02）：surname / source / evidence / place / migration_event / audit
└─ services/      业务逻辑（C-03 导入、C-04 查询、C-05 检索）
rag/              检索、提示词、校验、降级（E-01 — E-04）
search/           搜索服务（E-01）
tests/            契约形状、健康检查、迁移与查询测试（用真实迁移建测试库）
```