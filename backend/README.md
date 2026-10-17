# backend/ — FastAPI 后端

主责：**C**（`backend/app/`、`migrations/`）。`backend/rag/` 与 `backend/search/` 主责是 **E**。
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

## 当前实现状态（框架阶段）

| 部分 | 状态 |
| --- | --- |
| `/api/health` | 可用：真实探测数据库，模型/向量缺失时报 `degraded` |
| `/api/surnames/*` 五个查询接口 | **契约形状的空结果**（`coverage.status = "not_in_corpus"`），等 C-04 接入数据库后替换 |
| `POST /api/ask` | 返回 `degraded_no_model`，等 E-03/E-04 接入检索与校验 |
| `POST /api/admin/*` | 鉴权已实现，业务逻辑返回 501，等 C-03/C-05 |
| `backend/rag/*` | 只有接口签名与提示词骨架，实现归 E |
| `backend/search/*` | 待实现（E-01） |
| `app/models/*` | 待实现（C-02），表结构必须通过 Alembic 迁移创建 |

空结果是**有意为之**：这样 D 可以立刻开发加载态与未收录页面，C 接入数据后同一份前端代码直接显示真实内容，不需要改字段。

## 边界（违反会被打回）

- 只由 `app/services/` 与 `backend/search/` 访问数据库；路由层不直接写 SQL。
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
├─ api/           路由：health / surnames / ask / admin
├─ db/            连接与健康探测
├─ models/        ORM 模型（C-02）
└─ services/      业务逻辑（C-04 / C-05）
rag/              检索、提示词、校验、降级（E-01 — E-04）
search/           搜索服务（E-01）
tests/            契约形状测试与健康检查测试
```