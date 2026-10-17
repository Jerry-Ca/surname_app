# migrations/ — Alembic 数据库迁移（C 主责，任务 C-01 / C-02）

表结构的唯一变更通道。**禁止**用 `Base.metadata.create_all()` 建表（[../AGENTS.md](../AGENTS.md) 铁律 5）。

字段与表定义依据：[../docs/data-dictionary.md](../docs/data-dictionary.md) 第 2 节（**13 张表** + 状态字段 + 索引；该节曾写作“12 张表”，实际列出 13 张，含 `embedding_chunks` 与 `ingestion_jobs`）。

## 初始化（C-01，在 backend/ 下执行）

```bash
cd backend
alembic init -t generic ../migrations      # 生成 env.py 与 alembic.ini
```

然后把 `alembic.ini` 中的 `sqlalchemy.url` 改为从环境变量读取（不要写死连接串）：

```ini
# alembic.ini
sqlalchemy.url =
```

```python
# migrations/env.py 关键改动
from app.config import get_settings
from app.db.base import Base          # C-02 创建：声明 Base 与导入全部模型

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

## 生成与执行

```bash
cd backend
alembic revision --autogenerate -m "0001 initial schema"   # 生成迁移
alembic upgrade head                                        # 执行
alembic downgrade -1                                        # 回滚一步（必须可用）
alembic current                                             # 查看当前版本（/api/health 的 migration_revision 同源）
```

## 验收标准（C-02）

- [ ] 在**空库**上 `alembic upgrade head` 一次建齐 13 张表、外键、状态字段与索引
- [ ] `alembic downgrade base` 能干净回滚
- [ ] 重复执行 `upgrade head` 不报错（幂等）
- [ ] `/api/health` 的 `database.migration_revision` 显示当前版本号
- [ ] 迁移文件已提交，且**不包含任何数据内容**（数据一律走 `scripts/import_data.py`）

## 约束

- 一个迁移只做一件事；生产库上不做破坏性操作（删列/改类型）而不先备份。
- 迁移文件名保持 `0001_initial` 之类的顺序前缀，便于人工核对。
- 任何表结构变更必须同步更新 `docs/data-dictionary.md`，两者不一致时以文档为准并回滚代码。