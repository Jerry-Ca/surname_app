# 接口契约 v1（C 输出 / D 消费的唯一依据）

前端**不得**猜测数据库结构，后端**不得**在未更新本文件的情况下改字段。
变更流程：先改本文件 → 再改代码 → PR 中 @D 与 @E 确认 → 合并。

> 示例中的书名、卷次、摘录均为**结构占位**，不代表任何真实文献内容。真实数据必须由 B 回看原文后提供。

## 1. 通用约定

| 项目 | 规定 |
| --- | --- |
| Base path | `/api` |
| 传输 | HTTP + JSON（UTF-8），同源部署，前端经 Vite 代理或 Nginx 反代访问 |
| 字段命名 | `snake_case`，字段名与 [data-dictionary.md](data-dictionary.md) 一致 |
| 时间戳 | ISO 8601 UTC，如 `2026-10-17T03:21:00Z` |
| 年份 | 整数，公元前为负数；不精确时用 `year_start`/`year_end` 区间 + `time_label` |
| 分页 | 列表接口支持 `?page=1&page_size=20`（`page_size` 上限 100） |
| 缓存 | 结构化查询接口返回 `Cache-Control: public, max-age=60`；`/api/ask` 不缓存 |
| 鉴权 | 查询类接口无需鉴权；`/api/admin/*` 需要请求头 `X-Admin-Token` |

### 1.1 关于“查不到”

**未收录姓氏不是错误。** 输入合法的中文姓氏但语料中没有记录时：

- 一律返回 **HTTP 200** + 空结果结构 + `coverage` 字段说明查询范围与未命中原因；
- 前端据此渲染“已查询范围 + 语料审计”，不允许出现空白页；
- 只有**输入非法**（空、非汉字、超长）才返回 400。

这条规则决定了整个前端的错误处理结构，C 与 D 都不要改动。

### 1.2 错误结构

```json
{
  "error": {
    "code": "INVALID_SURNAME_INPUT",
    "message": "姓氏输入无效：仅支持 1—8 个汉字",
    "details": { "input": "123", "reason": "not_chinese" },
    "request_id": "req_20261017_0001"
  }
}
```

| HTTP | `code` | 触发条件 |
| --- | --- | --- |
| 400 | `INVALID_SURNAME_INPUT` | 空输入、非汉字、超过 8 字 |
| 404 | `ENDPOINT_NOT_FOUND` | 路径不存在 |
| 422 | `VALIDATION_ERROR` | 请求体字段缺失或类型错误（FastAPI 默认结构也归入此类） |
| 401 | `ADMIN_UNAUTHORIZED` | `/api/admin/*` 缺失或错误的 `X-Admin-Token` |
| 500 | `INTERNAL_ERROR` | 未预期异常，响应含 `request_id` 便于查日志 |
| 503 | `DATABASE_UNAVAILABLE` | 数据库不可用（健康检查会同时报 `database.connected=false`） |

`/api/ask` 在模型不可用时**不返回 5xx**，改为返回 200 且 `answer_mode = "degraded_no_model"`（见第 8 节）。

## 2. 公共对象

### 2.1 `SourceRef`（来源引用）

```json
{
  "source_code": "SRC-014",
  "work_title": "示例书名",
  "work_author": "示例作者",
  "dynasty": "示例朝代",
  "work_type": "official_history",
  "edition": "示例版本",
  "volume_or_section": "示例卷次或篇章",
  "page_or_location": "示例页码或定位",
  "source_provider": "示例平台",
  "source_url": "https://example.org/item/1",
  "accessed_at": "2026-10-17T03:21:00Z",
  "license_status": "public_domain",
  "link_status": "ok",
  "support_type": "direct"
}
```

### 2.2 `EvidenceSummary`（证据摘要，列表用）

```json
{
  "evidence_code": "EV-LI-001",
  "evidence_type": "earliest_attestation",
  "claim_text": "示例：一句话事实结论（须与原文一致）",
  "original_excerpt": "示例：原文短摘录",
  "volume_or_section": "示例卷次",
  "year_start": -11,
  "year_end": 25,
  "time_label": "示例：原文的时间表述",
  "verification_status": "verified",
  "confidence": "high",
  "sources": [ /* SourceRef[]，至少 1 条 */ ]
}
```

### 2.3 `Coverage`（查询覆盖情况，每个查询接口都返回）

```json
{
  "status": "in_corpus",
  "queried_corpora": ["示例语料 A", "示例语料 B"],
  "matched_surname": "李",
  "match_type": "exact",
  "total_evidences": 12,
  "verified_count": 9,
  "disputed_count": 1,
  "pending_count": 0,
  "note": null
}
```

`status` 取值：`in_corpus`（已收录）/ `not_in_corpus`（语料中未收录）/ `alias_matched`（通过别名或异体匹配到）。
`match_type` 取值：`exact` / `alias` / `variant` / `compound` / `none`。

### 2.4 `PlaceRef`

```json
{
  "historical_name": "示例古地名",
  "modern_name": "示例今地名",
  "period": "示例时期",
  "location_status": "approximate",
  "coordinates": null,
  "location_note": "示例：定位依据或无法定位的原因"
}
```

### 2.5 `Pagination`（列表接口）

```json
{ "page": 1, "page_size": 20, "total": 7, "has_more": false }
```

## 3. GET /api/health

用于本地启动自检与服务器健康检查（E 的部署脚本依赖此接口）。

```json
{
  "status": "ok",
  "api_version": "1.0.0",
  "git_sha": "fc74bd1",
  "database": { "connected": true, "dialect": "postgresql", "migration_revision": "0001_initial" },
  "model": {
    "configured": true, "provider": "deepseek", "model": "deepseek-chat",
    "embedding_configured": false
  },
  "degraded": ["embedding_unavailable"],
  "checked_at": "2026-10-17T03:21:00Z"
}
```

- `status`：`ok` / `degraded` / `down`。数据库不可用为 `down`（HTTP 503）；模型或向量缺失为 `degraded`（HTTP 200）。
- `degraded` 数组取值：`model_unavailable` / `embedding_unavailable` / `database_unavailable`。

## 4. GET /api/surnames/{name}

姓氏总览，前端结果页首屏只用这一个接口。

**请求**：`name` 为姓氏（支持繁体、异体、复姓），如 `/api/surnames/欧阳`。

**响应 200**：

```json
{
  "surname": {
    "canonical_name": "示例姓氏",
    "category": "compound",
    "status": "published",
    "description": "示例简介（只写可考信息）",
    "aliases": [ { "alias_name": "示例别名", "alias_type": "variant", "note": null } ],
    "matched_input": "欧阳",
    "match_type": "compound"
  },
  "coverage": { /* Coverage */ },
  "summary": {
    "earliest": { /* EvidenceSummary，可为 null */ },
    "commandery_count": 3,
    "migration_count": 2,
    "corpus_check_count": 4
  },
  "data_quality": {
    "verified_ratio": 0.75,
    "has_disputed": true,
    "stale_link_count": 1,
    "retracted_count": 0,
    "last_reviewed_at": "2026-10-17T03:21:00Z",
    "caveats": ["示例：本姓氏郡望存在多种说法，已并列展示"]
  },
  "degraded": []
}
```

- `earliest` 为 `null` 时前端显示“当前语料中未找到最早书证”，而不是报错。
- `data_quality.caveats` 是给前端的提示语数组，前端原样展示，不要自行改写措辞。

## 5. GET /api/surnames/{name}/earliest

最早书证。**必须返回排序依据**，让用户知道“最早”是怎么得出的。

```json
{
  "surname": "示例姓氏",
  "coverage": { /* Coverage */ },
  "items": [ /* EvidenceSummary[]，按 sort_basis.rule 排序 */ ],
  "sort_basis": {
    "rule": "verified_first_then_year_start",
    "note": "按已核对优先、year_start 升序；无 year_start 的记录排在最后并单独标注",
    "candidates_considered": 5,
    "excluded": [ { "evidence_code": "EV-LI-009", "reason": "pending" } ]
  },
  "statement": "当前语料中可以确认的最早书证为……",
  "statement_type": "earliest_in_corpus"
}
```

- `statement_type`：`earliest_in_corpus`（仅能确认“当前语料中最早”）/ `insufficient_evidence`。
- 前端必须按 `statement_type` 选择措辞，不允许把 `earliest_in_corpus` 渲染成绝对结论。

## 6. GET /api/surnames/{name}/commanderies

历史郡望，多个说法并列。

```json
{
  "surname": "示例姓氏",
  "coverage": { /* Coverage */ },
  "items": [
    {
      "commanderies_code": "EV-LI-002",
      "name": "示例郡望名",
      "period": "示例时期",
      "time_label": "示例时间表述",
      "year_start": null,
      "year_end": null,
      "dispute_group": "DG-LI-01",
      "is_disputed": true,
      "verification_status": "disputed",
      "confidence": "medium",
      "evidence": { /* EvidenceSummary */ }
    }
  ],
  "pagination": { "page": 1, "page_size": 20, "total": 1, "has_more": false },
  "dispute_groups": [
    { "dispute_group": "DG-LI-01", "summary": "示例：两种说法并存的原因", "positions": ["说法 A", "说法 B"] }
  ]
}
```

- 同一 `dispute_group` 的条目**必须全部返回**，前端并列展示，不排序成“推荐项”。
- `is_disputed=true` 的条目不允许被前端过滤掉。

## 7. GET /api/surnames/{name}/migrations

迁徙线索。

```json
{
  "surname": "示例姓氏",
  "coverage": { /* Coverage */ },
  "items": [
    {
      "migration_code": "MG-LI-001",
      "time_label": "示例：时间段表述",
      "year_start": null,
      "year_end": null,
      "from_place": { /* PlaceRef */ },
      "to_place": { /* PlaceRef */ },
      "event_summary": "示例：发生了什么迁移（须有文献依据）",
      "relation_status": "disputed",
      "confidence": "low",
      "evidences": [
        { "evidence_code": "EV-LI-005", "relation_type": "circumstantial", "support_type": "circumstantial" }
      ]
    }
  ],
  "pagination": { "page": 1, "page_size": 20, "total": 0, "has_more": false },
  "empty_message": "当前资料中未找到可核对的迁徙线索"
}
```

- 无迁徙记录时返回空数组 + `empty_message`（HTTP 200）。文案由后端给出，前端直接展示。
- 地点 `location_status=unlocatable` 时 `coordinates` 必须为 `null`，**不得伪造坐标**。

## 8. POST /api/ask

证据问答。请求：

```json
{ "surname": "示例姓氏", "question": "示例问题", "top_k": 8 }
```

响应 200：

```json
{
  "answer": "示例回答，句末带 [EV-LI-001] 形式的证据编号",
  "answer_mode": "evidence_grounded",
  "abstained": false,
  "abstain_reason": null,
  "citations": [
    {
      "evidence_code": "EV-LI-001",
      "work_title": "示例书名",
      "volume_or_section": "示例卷次",
      "original_excerpt": "示例原文短摘录",
      "source_url": "https://example.org/item/1",
      "verification_status": "verified",
      "confidence": "high"
    }
  ],
  "retrieved_count": 6,
  "model": { "provider": "deepseek", "model": "deepseek-chat", "latency_ms": 1830 },
  "notice": null
}
```

规则：

| 情况 | `answer_mode` | `abstained` | 其他字段 |
| --- | --- | --- | --- |
| 正常，回答含证据编号且引用的编号都在 `citations` 中 | `evidence_grounded` | `false` | — |
| 检索结果为空 | `insufficient_evidence` | `true` | `answer = "当前资料不足以确认"`，`abstain_reason = "no_evidence"` |
| 模型 Key 缺失 / 调用失败 | `degraded_no_model` | `true` | `notice = "智能摘要暂不可用，结构化证据仍可查询"`，`citations` 仍返回检索到的证据 |
| 回答不含证据编号或出现新事实 | `insufficient_evidence` | `true` | `abstain_reason = "ungrounded_answer"`，原回答不得作为结论显示 |

- `top_k` 默认 8，范围 1—20。
- 任何情况下都不得返回 5xx；模型故障由 `answer_mode` 表达。
- 证据不足的固定回答文案：**当前资料不足以确认**（前端不要自行改写）。

## 9. POST /api/admin/import

导入已核对数据（仅 C 与 B 在服务器上使用）。

请求头：`X-Admin-Token: <ADMIN_TOKEN>`（服务器环境变量）。

```json
{
  "input_ref": "data/verified/evidences.csv",
  "dry_run": true,
  "operator": "B",
  "stage": "load"
}
```

响应 200：

```json
{
  "job_id": "JOB-20261017-001",
  "stage": "load",
  "total": 100,
  "accepted": 97,
  "rejected": 3,
  "errors": [
    { "row": 42, "field": "source_url", "reason": "缺少来源链接且未填 access_note" }
  ],
  "rolled_back": false,
  "started_at": "2026-10-17T03:21:00Z",
  "finished_at": "2026-10-17T03:21:04Z"
}
```

- `dry_run=true` 只校验不写库；B 交付数据包时先用它验收。
- 任一记录校验失败即整体不写入（`rolled_back=true`），并把错误行写回 `ingestion_jobs.error_log`。

## 10. POST /api/admin/reindex

重建全文与向量索引。

```json
{ "mode": "all" }
```

```json
{
  "fulltext": { "indexed": 100, "failed": 0, "skipped": 2 },
  "vector": { "indexed": 0, "failed": 0, "skipped": 100, "reason": "embedding_unavailable" },
  "duration_ms": 4210,
  "degraded": ["embedding_unavailable"]
}
```

`mode` 取值 `fulltext` / `vector` / `all`。向量不可用时返回 `skipped` + `reason`，不报错，保证核心功能不被阻塞。

## 11. GET /api/surnames/{name}/corpus-checks

语料审计（方案第 1.1 节的四项硬性输出之一）：说明查过哪些语料、用什么查询词、得到多少结果、为什么没查到。
未收录姓氏的页面表现完全依赖本接口，因此**必须返回 queried_corpora 与 no_result_reason，不能返回空对象**。

**请求**：`?page=1&page_size=20`（与第 6、7 节同一套分页规则）。

**响应 200**：

```json
{
  "surname": "示例姓氏",
  "coverage": { /* Coverage */ },
  "items": [
    {
      "search_code": "CS-LI-001",
      "corpus_name": "示例语料平台",
      "query_text": "李",
      "checked_at": "2026-10-17T03:21:00Z",
      "result_count": 0,
      "no_result_reason": "该平台无全文检索，仅能按书名浏览",
      "operator": "B",
      "note": null
    }
  ],
  "pagination": { "page": 1, "page_size": 20, "total": 1, "has_more": false },
  "summary": { "corpora_checked": ["示例语料平台"], "total_queries": 1, "total_results": 0 }
}
```

规则：

| 项目 | 规定 |
| --- | --- |
| 排序 | `checked_at` 倒序，同时间按 `search_code` 升序（稳定排序，便于前端对照） |
| `result_count = 0` | `no_result_reason` 必填（数据字典与 `validate_data.py` 都会拦），页面据此说明未命中原因 |
| 未收录姓氏 | 返回 200 + 空 `items` + `coverage.status = "not_in_corpus"`，`summary` 仍给出查询次数与覆盖语料 |
| `summary.corpora_checked` | 去重后的语料名列表，前端直接展示“已查询范围” |
| `note` | 补充说明，可为 `null` |

> 章节号说明：本接口与第 4—7 节同属查询类接口，但编号排在最后，因为第 8—10 节已被 C/E/D 的代码注释大量引用（例如“契约第 8 节”指 `/api/ask`）。为避免一次性改错几十处注释，这里不改动既有编号。

## 12. 前端调用规则（D 必读）

1. 所有请求走 `frontend/src/api/client.js`，不得在组件里散写 `fetch`。
2. 必须处理的返回形态：`200 正常` / `200 空结果（coverage.status = not_in_corpus）` / `200 降级（answer_mode = degraded_no_model）` / `4xx 错误` / `5xx 服务不可用`。
3. 页面不得出现空白页：空结果必有解释文案，错误必有重试入口。
4. 界面文案与状态枚举的对应关系见 [data-dictionary.md](data-dictionary.md) 第 3、7 节。
5. 前端永远不接触 DeepSeek / Embedding 的 Key（[AGENTS.md](../AGENTS.md) 铁律 4）。

## 13. 契约自检清单（评审 PR 时逐项核对）

- [ ] 字段名与本文件一致，没有多余的临时字段
- [ ] 空结果返回 200 + `coverage`，不是 404 或 `null`
- [ ] 有争议数据全部返回，未被过滤或合并
- [ ] 时间不精确时使用区间 + `time_label`，没有伪造年份
- [ ] 地点无法定位时 `coordinates` 为 `null`
- [ ] 语料审计接口：`result_count = 0` 时 `no_result_reason` 非空，`summary.corpora_checked` 非空
- [ ] `/api/ask` 在模型不可用时返回 `degraded_no_model`，不是 500
- [ ] 新增/变更字段已同步更新本文件