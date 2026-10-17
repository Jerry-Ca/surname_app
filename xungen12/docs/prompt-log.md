# Prompt Log（成员 C）

要求（执行清单 §八）：记录时间、提示词摘要、AI 输出、人工核验与结论。**只记录真实发生的事**。

| 时间（UTC） | 提示词摘要 | AI 输出 | 人工核验与结论 |
| --- | --- | --- | --- |
| 2026-10-17T09:16 | 让智能体按《成员C SQLite 后端与接口执行清单》把后端改成标准库 + SQLite，先给建库与导入脚本 | 生成 `app/schema.py`（10 张表 + CHECK 约束）、`scripts/init_db.py`、`app/validation.py`、`scripts/validate_package.py`、`scripts/import_data.py` | 逐条核对：约束是否覆盖执行清单 §一.4（evidence_id 唯一、原文/来源/链接必填、状态五值）；实测手工插入空原文/非法状态/年份倒置均被拦；导入 12 条样例通过、重复导入被拒。采纳。 |
| 2026-10-17T09:18 | 报错：`GET /api/surnames/李` 返回 500，附 `logs/app.log` 栈（`AttributeError: 'str' object has no attribute 'execute'`） | 定位为 `app/queries.py` 里 10 处 `db.query_*` 调用漏传连接对象，给出全量替换补丁 | 按补丁修完重跑：接口返回 200 且四类数据齐全；另加了「漏传 connection」的静态排查命令，复查无残留。采纳。 |
| 2026-10-17T09:19 | 报告：按未收录姓氏检索却命中了别的姓氏的证据，要求判断是测试写错还是实现有问题 | 判定为实现的边界缺陷（未收录姓氏时退化成全库检索），给出在指定姓氏不可解析时直接返回空结果的补丁 | 复测：`/api/search?q=…&surname=欧` 返回空数组 + 说明；契约测试与单元测试均通过。采纳。 |
| 2026-10-17T09:21 | 让智能体写契约测试（每个 /api/* 存 request/response 并校验形状） | 生成 `scripts/contract_tests.py`：临时库 + 临时端口 + 真实 HTTP 请求，15 项检查 | 实测 15/15 通过，`docs/contract/` 生成 14 份接口样例；确认测试期间已清空模型 Key（不会调外部接口）。采纳。 |

## 踩坑与被推翻的记录

| 时间 | 提示词摘要 | AI 输出 | 结论 |
| --- | --- | --- | --- |
| 2026-10-17T09:06 | 让智能体把 FTS5 索引建在导入前 | 默认分词器（unicode61）的建表语句 | 推翻：unicode61 把连续汉字当成一个词，中文子串检索无效。改为 `tokenize='trigram'`，并用「陇西/陇西郡望」实测验证；旧版 SQLite 不支持 trigram 时回落 LIKE。 |
| 2026-10-17T09:33 | 用户告知「服务器上是 python3.10.12」，要求据此确认兼容性 | 指出第一版用了 `datetime.UTC`（3.11+），给出改成 `timezone.utc` 的补丁；并提示 ruff 若目标版本是 py312 会把改动"修回去" | 实测印证：ruff 确实把 `timezone.utc` 升回了 `datetime.UTC`（pyupgrade 规则），于是把 `target-version` 降到 py38；另外用 `ast.parse(feature_version=(3,10))` 逐个文件校验、逐项核对用到的标准库成员，并把这三条做成 `tests/test_compat.py` 常驻护栏。采纳。 |

