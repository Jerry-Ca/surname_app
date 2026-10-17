# 数据字典 v1（冻结于 Day1，字段命名唯一来源）

本文件定义**字段名、枚举值、编号规则**。数据库表、后端 API、前端展示、CSV 导出必须全部使用这里的名称。
任何新增字段先改本文件，再改代码（流程见 [CONTRIBUTING.md](../CONTRIBUTING.md) 第 6 节）。

> 警告：本文件只定义**结构**。文中的示例值（书名、卷次、摘录）仅用于说明字段用途，**不构成数据**。B 必须逐条回看原文后填写真实内容。

## 1. 命名约定

- 字段名一律 `snake_case`，英文小写下划线，不用拼音、不用中文键名。
- 时间字段用整数年：公元前为负数（公元前 100 年 = `-100`），无公元纪年概念的用 `null`。
- 时间不精确时**不猜测具体年份**：`year_start` / `year_end` 组成区间，`time_label` 保存原文的表述（如“唐初”“约东汉中后期”）。
- 所有时间戳字段 `*_at` 用 ISO 8601 UTC 字符串：`2026-10-17T03:21:00Z`。
- 布尔字段以 `is_` / `has_` 开头。
- 金额、数量等不要用字符串；缺失值统一 `null`，不要用空字符串 `""` 或 `"未知"`。

## 2. 表与关键字段

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `surnames` | 姓氏本身 | `id`、`canonical_name`、`category`（单姓/复姓）、`status`、`description` |
| `surname_aliases` | 别名与异体 | `surname_id`、`alias_name`、`alias_type`、`note` |
| `source_works` | 文献作品 | `title`、`author`、`dynasty`、`work_type` |
| `source_editions` | 具体版本与来源 | `work_id`、`edition`、`publisher`、`source_provider`、`source_url`、`license_status`、`accessed_at`、`content_hash` |
| `evidences` | 原子证据 | `surname_id`、`evidence_type`、`claim_text`、`original_excerpt`、`volume_or_section`、`year_start`、`year_end`、`verification_status`、`confidence`、`verified_by` |
| `evidence_sources` | 证据与文献关系 | `evidence_id`、`source_edition_id`、`citation_detail`、`page_or_location`、`support_type` |
| `places` | 历史地点 | `historical_name`、`modern_name`、`period`、`coordinates`、`location_status`、`location_note` |
| `migration_events` | 迁徙事件 | `surname_id`、`from_place_id`、`to_place_id`、`time_label`、`year_start`、`year_end`、`relation_status`、`confidence` |
| `migration_event_evidences` | 迁徙事件证据 | `migration_event_id`、`evidence_id`、`relation_type` |
| `corpus_searches` | 语料审计 | `surname_id`、`corpus_name`、`query_text`、`checked_at`、`result_count`、`no_result_reason`、`operator` |
| `review_logs` | 人工修改历史 | `target_type`、`target_id`、`action`、`reviewer`、`before_json`、`after_json`、`review_note` |
| `embedding_chunks` | 向量检索片段 | `evidence_id`、`chunk_text`、`provider`、`model`、`embedding_vector`、`dimensions` |
| `ingestion_jobs` | 数据导入任务 | `source`、`stage`、`input_ref`、`total`、`accepted`、`rejected`、`error_log`、`started_at`、`finished_at` |

## 3. 枚举值（代码值 ↔ 界面中文）

API 与数据库一律存**左侧代码值**，界面显示右侧中文。禁止在界面直接显示代码值，禁止在数据库里存中文。

### 3.1 核对状态 `verification_status`（核心枚举）

| 代码值 | 界面中文 | 含义 | 是否可公开发布 |
| --- | --- | --- | --- |
| `verified` | 已核对 | 人工确认书名、卷次、原文与来源链接 | 可以 |
| `pending` | 待核对 | 已发现候选记录，尚未回看原文 | 不可以（仅内部） |
| `disputed` | 有争议 | 存在多个说法，全部保留，不自动合并 | 可以，必须并列展示 |
| `link_stale` | 链接待复查 | 文献记录保留，原链接当前不可访问 | 可以，必须提示链接待复查 |
| `retracted` | 已撤回 | 误引或无法证明，保留记录与撤回原因 | 可以，必须显示已撤回与原因 |

### 3.2 其他枚举

| 字段 | 代码值 | 界面中文 |
| --- | --- | --- |
| `evidence_type` 事实类型 | `earliest_attestation` / `commandery` / `migration` / `other` | 最早书证 / 郡望 / 迁徙 / 其他 |
| `confidence` 可信度 | `high` / `medium` / `low` | 高 / 中 / 低 |
| `support_type` 支持方式 | `direct` / `circumstantial` / `genealogy` | 直接证据 / 旁证 / 谱牒证据 |
| `relation_type` 事件—证据关系 | `direct` / `circumstantial` / `genealogy` / `conflicting` | 直接证据 / 旁证 / 谱牒证据 / 相互矛盾 |
| `relation_status` 事件关系状态 | `agreed` / `disputed` / `unclear` | 无争议 / 有争议 / 关系不明确 |
| `alias_type` 别名类型 | `variant` / `honorific` / `traditional_simplified` / `other` | 异体或异写 / 氏称 / 繁简对应 / 其他 |
| `work_type` 文献类型 | `official_history` / `surname_book` / `local_gazetteer` / `classic` / `other` | 正史 / 姓氏书 / 方志 / 经典文献 / 其他 |
| `license_status` 授权状态 | `public_domain` / `platform_terms_ok` / `restricted_excerpt_only` / `unknown` | 公有领域 / 平台条款允许 / 仅可短摘录 / 未知 |
| `location_status` 定位状态 | `located` / `approximate` / `unlocatable` | 已定位 / 大致范围 / 无法定位 |
| `link_status` 链接状态 | `ok` / `stale` | 正常 / 待复查 |
| `category` 姓氏类别 | `single` / `compound` | 单姓 / 复姓 |
| `answer_mode` 问答模式 | `evidence_grounded` / `degraded_no_model` / `insufficient_evidence` | 基于证据回答 / 模型不可用（降级） / 证据不足 |
| `ingestion stage` 导入阶段 | `fetch` / `clean` / `verify` / `load` / `index` | 抓取 / 清洗 / 核验 / 入库 / 建索引 |

## 4. 编号规则

编号一旦生成不得回收、不得复用（撤回的记录保留原编号并标 `retracted`）。

| 对象 | 格式 | 示例 | 说明 |
| --- | --- | --- | --- |
| 证据 | `EV-{姓氏拼音大写}-{3 位序号}` | `EV-LI-001` | 复姓用连字符：`OUYANG-`、`SI-MA-` |
| 迁徙事件 | `MG-{姓氏拼音大写}-{3 位序号}` | `MG-LI-002` | 与证据编号独立计数 |
| 语料审计 | `CS-{姓氏拼音大写}-{3 位序号}` | `CS-LI-001` | 一次查询一条 |
| 来源版本 | `SRC-{3 位序号}` | `SRC-014` | 对应 `data/source_register.csv` 的行 |
| 导入任务 | `JOB-{yyyyMMdd}-{3 位序号}` | `JOB-20261017-001` | 由导入脚本生成 |

正则（CI 会校验）：`^EV-[A-Z-]+-\d{3}$`、`^MG-[A-Z-]+-\d{3}$`、`^CS-[A-Z-]+-\d{3}$`、`^SRC-\d{3}$`。

## 5. 每条证据的最低字段（方案 6.2 的落地版本）

`data/verified/evidences.csv` 必须包含且填满以下列，缺任一项 CI 判定失败：

| CSV 列 | 对应字段 | 必填规则 |
| --- | --- | --- |
| `evidence_code` | 证据编号 | 必填，符合编号规则 |
| `surname` | 关联姓氏 | 必填，与 `surnames.canonical_name` 一致 |
| `evidence_type` | 事实类型 | 必填，取 3.2 枚举 |
| `work_title` | 文献书名 | 必填（`verification_status=verified` 时） |
| `work_author` | 作者或编者 | 必填或填 `佚名`/`未详`，不得留空 |
| `volume_or_section` | 卷次、章节或页码 | 必填，不得写“见原文” |
| `original_excerpt` | 原文短摘录 | 必填，禁止改写或补齐，禁止使用省略号替代整段 |
| `source_url` | 来源链接 | 必填或说明为何无法提供（如纸本），此时必须填 `access_note` |
| `source_code` | 来源版本编号 | 必填，须在 `source_register.csv` 中存在 |
| `accessed_at` | 访问时间 | 必填，ISO 8601 |
| `verification_status` | 核对状态 | 必填，进入 `data/verified/` 的只能写 `verified`/`disputed`/`link_stale`/`retracted` |
| `confidence` | 可信度 | 必填 |
| `verified_by` | 操作人 | 必填，写真实成员代号或姓名 |
| `verification_note` | 人工核验说明 | 必填，写清核对了什么、哪里存疑 |
| `claim_text` | 事实结论（一句话） | 必填，须与原文一致，不得加入原文没有的推断 |
| `year_start` / `year_end` | 年代区间 | 可空；有值时必须是整数年，`year_start <= year_end` |
| `dispute_group` | 争议分组 | `verification_status=disputed` 时必填，同组多说法共用一个值 |

## 6. 数据状态流转

```
候选发现 ──► pending（待核对，仅存 data/raw）
                │  人工回看原文
                ▼
             verified（已核对，入 data/verified）
                ├──► disputed（发现多种说法，并列保留）
                ├──► link_stale（链接失效，元数据与摘录保留）
                └──► retracted（误引或无法证明，保留原因）

任何状态都不物理删除。状态变更必须写入 review_logs（谁、何时、改了什么、为什么）。
```

## 7. 前端展示要求（与状态枚举绑定）

| 状态 | 页面必须显示 |
| --- | --- |
| `verified` | 正常证据卡片，显示来源链接 |
| `disputed` | 并列卡片 + “存在争议”标记，界面不得提供“选一个”的默认操作 |
| `link_stale` | 保留书名、卷次、原文、访问时间，标注“链接待复查” |
| `retracted` | 灰显 + 撤回原因，不得作为结论参与展示 |
| `pending` | 前端不应收到该状态的数据（后端过滤），若收到则标注“未核对，仅供参考” |

## 8. 校验与门禁

- `scripts/validate_data.py`（CI 的 `data-check` 作业）按本文件第 4、5 节校验编号格式与必填字段。
- `scripts/import_data.py` 在校验基础上增加外键存在性、重复证据与非法年份检查。
- 任何绕过校验直接写库的操作都视为违规（[AGENTS.md](../AGENTS.md) 铁律 5）。