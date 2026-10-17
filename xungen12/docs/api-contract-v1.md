# 接口契约 v1（草案，C 起草，待 A 冻结）

本文件是共享服务器版（Python 标准库 + SQLite）的接口唯一依据。字段名与形状改动**必须**先改本文件，
再改代码，并通知 A/D/E（执行清单 §三.12）。与 `docs/api-contract.md`（FastAPI/PostgreSQL 路线）并存，
但**只有本文件对应实际交付的服务**。

示例里的书名、卷次、摘录均为结构占位，不是真实史料。

## 1. 通用约定

| 项目 | 规定 |
| --- | --- |
| Base path | `/api` |
| 传输 | HTTP + JSON（UTF-8）；**页面与接口同源、同一个端口**（站外 `http://<公网IP>:18888/` 是网页，`/api/*` 是接口），前端请用相对路径 `/api/...` 调用，不要写死 IP，也不需要 CORS |
| 成功响应 | **恒为三个键**：`data` / `audit` / `message` |
| `data` | 主体，数组或对象；空结果一律 `[]`（不是 `null`、不是 404） |
| `audit` | 查了什么、命中多少、为什么没查到、分页信息；列表接口必有 `pagination` |
| `message` | 给人看的一句话（空结果原因、降级提示、待核对提示），可为 `null` |
| 时间戳 | ISO 8601 UTC，如 `2026-10-17T03:21:00Z` |
| 年份 | 整数，公元前为负数；不精确时用 `year_start`/`year_end` + `time_label` |
| 分页 | `?page=1&page_size=20`，`page>=1`、`1<=page_size<=100`，越界返回 422 |
| 缓存 | 查询类返回 `Cache-Control: public, max-age=60`；`/api/ask` 与错误响应 `no-store` |
| 鉴权 | 查询与问答都不需要鉴权；写库只通过命令行脚本，**没有**写接口 |

### 1.1 未收录不是错误

输入合法的中文姓氏但库里没有可展示证据时：**HTTP 200** + `data: []`（或总览里的空字段）+
`audit.coverage = "not_in_corpus"` + `message` 说明已查过的语料与未命中原因。前端据此渲染
「已查询范围 + 语料审计」，不允许空白页。只有输入非法（空、非汉字、超长）才返回 400。

### 1.2 错误结构

```json
{"error": {"code": "INVALID_SURNAME_INPUT", "message": "姓氏输入无效：仅支持 1—8 个汉字",
           "details": {"input": "abc", "reason": "not_chinese_or_too_long"}}}
```

| HTTP | `code` | 触发条件 |
| --- | --- | --- |
| 400 | `INVALID_SURNAME_INPUT` | 空输入、非汉字、超过 8 字 |
| 404 | `ENDPOINT_NOT_FOUND` | 路径不存在，或静态路径被拒绝（数据库/日志/备份/密钥） |
| 422 | `VALIDATION_ERROR` | `page`/`page_size` 越界、查询词为空、请求体不是 JSON 对象、`top_k` 越界 |
| 500 | `INTERNAL_ERROR` | 未预期异常（日志里有时间点，交给 C 排查） |
| 503 | `DATABASE_UNAVAILABLE` | `data/xungen.db` 不存在或打不开（`/api/health` 同时报 `db.connected=false`） |

`/api/ask` 在模型不可用时**不返回 5xx**，返回 200 + `answer_mode = "unavailable"`（见第 5 节）。

## 2. 公共对象

### 2.1 `evidence`（证据条目，四类查询与检索共用）

```json
{
  "evidence_id": "EV-LI-001",
  "evidence_type": "earliest_attestation",
  "evidence_type_label": "最早书证",
  "claim_text": "一句话事实结论（须与原文一致）",
  "original_excerpt": "原文短摘录",
  "volume_or_section": "卷一",
  "page_or_location": "第 10 页",
  "year_start": -100, "year_end": 25, "time_label": "原文的时间表述",
  "verification_status": "verified", "verification_status_label": "已核对",
  "confidence": "high", "is_disputed": false, "dispute_group": null,
  "source": {
    "source_code": "SRC-001", "title": "书名", "author": "作者", "dynasty": "朝代",
    "work_type": "classic", "url": "https://example.org/a",
    "license_status": "public_domain", "accessed_at": "2026-10-17T00:00:00Z"
  }
}
```

`evidence_id` 与来源字段是硬要求：页面、问答、备份核对都靠它贯穿（执行清单 §十二）。

### 2.2 `audit`

```json
{
  "coverage": "in_corpus",
  "queried_corpora": ["语料甲", "语料乙"],
  "total_queries": 2, "total_results": 3, "no_result_reason": null,
  "counts": {"total": 5, "verified": 2, "disputed": 2, "pending": 0, "retracted": 1, "link_stale": 0, "publishable": 5},
  "pagination": {"page": 1, "page_size": 20, "total": 2, "has_more": false}
}
```

- `coverage`：`in_corpus`（有可对外发布的证据）/ `not_in_corpus` / `alias_matched`（别名匹配到主记录）；
  只有 `pending` 记录时按 `not_in_corpus` 返回，并在 `message` 说明「已查到 N 条但未通过人工核验」。
- `counts` 含 `pending`（仅计数、不外发条目），便于前端显示“另有 N 条待核对”。

## 3. 接口清单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查（字段见第 4 节，**非** data/audit/message 信封） |
| GET | `/api/surnames/{name}` | 姓氏总览：一次给出四类数据 |
| GET | `/api/surnames/{name}/earliest` | 最早书证（列表 + 排序依据） |
| GET | `/api/surnames/{name}/commanderies` | 郡望（争议并列） |
| GET | `/api/surnames/{name}/migrations` | 迁徙线索 |
| GET | `/api/surnames/{name}/corpus-checks` | 语料审计 |
| GET | `/api/search?q=&surname=` | 全文检索（结论/原文摘录/卷次） |
| POST | `/api/ask` | 证据问答（模型可选，降级见第 5 节） |

## 4. GET /api/health

```json
{"status": "ok", "db": {"path": "data/xungen.db", "connected": true, "schema_version": "1",
                        "tables": 10, "tables_expected": 10, "fts": "ready"},
 "version": "v1", "model_configured": false, "model": "deepseek-chat", "port": 18888,
 "checked_at": "2026-10-17T03:21:00Z"}
```

- `status`：`ok` / `degraded`（模型 Key 未配置）/ `down`（数据库不可用，HTTP 503）；
- **不返回**任何 API Key、连接串或环境变量值；`model_configured` 只是布尔值。

## 5. GET /api/surnames/{name}（总览）

`data` 为对象：`surname`、`earliest`（`evidence` 或 `null`）、`earliest_candidates`（含已撤回，供前端标注）、
`commanderies`、`migrations`、`corpus_checks`。`migrations` 条目：

```json
{"migration_code": "MG-LI-001", "time_label": "示例时段", "year_start": 600, "year_end": 700,
 "event_summary": "发生了什么迁移", "relation_status": "agreed", "confidence": "medium",
 "from_place": {"historical_name": "古地名", "modern_name": null, "period": null,
                "location_status": "approximate", "coordinates": null, "location_note": "定位依据"},
 "to_place": null,
 "evidences": [{"evidence_id": "EV-LI-002", "relation_type": null,
                "verification_status": "disputed", "confidence": "medium"}]}
```

无法定位的地点：`location_status = "unlocatable"` 且 `coordinates` 必须为 `null`（不伪造坐标）。

## 6. 排序与可见性（不变量）

1. **可见性**：`pending` 不出现在任何 `data` 列表里，只在 `audit.counts.pending` 与 `message` 里提示；
   `retracted` 可以查到，但**不得**作为「最早」的结论（只在 `earliest_candidates` 里出现，前端灰显并标注原因）。
2. **排序**（列表接口一致，可解释、可复现）：
   已核对优先 → 有来源优先 → 同一状态内有年份的在前（无年份排后）→ `year_start` 升序 → `evidence_id` 收敛。
3. **「最早」的判定**：绝不按数据库插入顺序。优先取有年份的记录；全部无年份时退回第一条，
   并在 `message` 里说明“没有明确年份，只能按 time_label 展示”。
4. **争议**：`disputed` 与 `dispute_group` 的记录**全部返回**，`is_disputed=true`，同组不合并、不排序成推荐项。

## 7. GET /api/search

- 检索范围：`claim_text`、`original_excerpt`、`volume_or_section`；
- 命中项带 `matched_field`（`claim_text`/`original_excerpt`/`volume_or_section`）与 `snippet`（原文子串，不生成）；
- `audit.retrieval = {"mode": "fts5"|"like", "query": "...", "note": null|"回落原因"}`：
  共享服务器上的 SQLite 没有 FTS5 时自动回落 LIKE，结果一致；
- 检索词按**字面量**处理：`%`、`_`、`\` 不做通配；
- 指定了 `surname` 但库里没有该姓氏时返回空结果 + 说明，**不退化成全库检索**。

## 8. POST /api/ask

请求：`{"surname": "李", "question": "郡望有哪些说法？", "top_k": 8, "evidence_ids": ["EV-LI-001"]}`（后两项可选）。

`answer_mode` 取值与行为：

| 情况 | `answer_mode` | `abstained` | 其他 |
| --- | --- | --- | --- |
| 正常，回答带 `[EV-xxx]` 且编号都在 `citations` 里 | `evidence_grounded` | `false` | — |
| 检索不到证据 | `insufficient_evidence` | `true` | `answer = "当前资料不足以确认"`，`citations: []` |
| 模型未配置或调用失败 | `unavailable` | `true` | **仍返回检索到的 `citations`**，`message` 说明原因 |
| 回答没有编号 / 引用了不存在的编号 | `insufficient_evidence` | `true` | `message` 说明弃答原因 |

任何情况下都不得返回 5xx；也不得把 Key、模型报错原文返回给前端。

## 9. 契约自检清单（评审用）

- [ ] 每个 `/api/*` 的响应都在 `docs/contract/*.json` 里有 request/response 样例
- [ ] `python3 scripts/contract_tests.py` 全绿（含形状比对）
- [ ] 空结果是 `data: []` + 200，不是 404/500
- [ ] `evidence` 条目都带 `evidence_id` 与 `source.url`
- [ ] `pending` 不出现在列表里；`retracted` 不作「最早」结论
- [ ] 争议记录全部返回且带 `is_disputed`
- [ ] 无法定位的地点 `coordinates` 为 `null`
- [ ] 字段有变化时，本文件先改、再改代码，并通知 A/D/E