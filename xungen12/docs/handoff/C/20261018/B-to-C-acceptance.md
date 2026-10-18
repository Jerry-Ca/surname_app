# B→C 交接验收记录（2026-10-18，成员 C 收）

按 `docs/collaboration/handoff.md` 第 1 节：**交接不是「发个链接」，接收方要在自己的环境里跑通并写下结果**。
本文件是 C 对 B 第 2 天交接（`HANDOFF-B-20261018.md`）的验收实测记录，全部输出来自 2026-10-18 在
共享服务器 `/home/ubuntu/guji-jiaocuo/xungen12` 与站外网络的真实执行。

- 交接方 / 接收方：**成员 B / 成员 C**
- 交接物：`HANDOFF-B-20261018.md`、`data/incoming/20261018-B{,-delta,-day3}/`、
  `docs/handoff/B/20261018/`（manifest / note-to-A-C / proposed-patches-for-C / contract-decision）、
  `scripts/B/apply_review_status.py`、`docs/run-log.md`
- 交接方自述口径：证据 110 条全部判定完（已核对 81 / 已撤回 29 / 待核对 0）、`review_logs` 110 条留痕、
  对外可见 74 条、契约测试 15/15、第 3 天补量 292 条 0 拒绝

## 1. 数据包校验（`python3 scripts/validate_package.py <包>`）

| 包 | 结果 |
| --- | --- |
| `data/incoming/20261018-B-delta` | 2 个文件、**300 条全部通过**（34 证据 + 266 语料审计） |
| `data/incoming/20261018-B-day3` | 3 个文件、**292 条全部通过**（160 证据 + 43 地名 + 89 语料审计） |
| `data/incoming/20261018-B` | 4 个数据文件 **355 条全部通过**；**整目录**校验报 2 条错误 —— 见第 5 节 |

## 2. 导入预演（`import_data.py`，**在正式库的临时副本上跑**，不污染正式库）

```bash
cp data/xungen.db data/tmp/c-accept/accept.db
XUNGEN_DB=data/tmp/c-accept/accept.db python3 scripts/import_data.py data/incoming/20261018-B --operator C
```

实测：`任务号 JOB-20261018-007｜dry-run（未写库）｜文件 6 个｜记录 355 条｜通过 0｜拒绝 252`，
拒绝项全部是**可读、可修复**的错误，两类：

- `证据编号已入库：EV-LIC-001（重复导入）（修复：编号不得复用；如确需更新记录，请先人工核验后走 review_logs 流程）`
  —— 共 248 条，证明包已被导入过、重跑不会重复写入；
- `live-api-samples.json / stats-v2.json：无法判断数据种类` —— 包目录混入辅助文件（第 5 节）。

副本被写入 JOB-20261018-007 后复查：正式库 `evidences=270`、`ingestion_jobs=8` 均未变；副本与临时文件已删除。

## 3. 库状态对照（B 的 manifest 数字 vs 实测）

| 项 | B 自述 | C 实测 | 一致 |
| --- | --- | --- | --- |
| evidences 总数 | 110 | 270（含第 3 天 160 条 pending） | ✓（B 口径为第 2 天的 110 条） |
| 已核对 / 已撤回 / 待核对 | 81 / 29 / 0（第 2 天） | 81 / 29 / 160（含第 3 天补量） | ✓ |
| `evidence_type` 分布 | commandery 23 + earliest 10 + other 48 已核对 | commandery 23 / earliest_attestation 10 / other 48 | ✓ |
| review_logs | 110 条留痕 | 110 | ✓ |
| evidences_fts | 110 | 110 | ✓ |
| surnames / places / corpus_searches | 101 / 70 / 5707 | 101 / 70 / 5707 | ✓ |
| 覆盖姓数 | 14 → 98（在册 101） | `count(distinct surname_id)=98` | ✓ |
| 导入任务 | 355/0、300/0、292/0 | `ingestion_jobs` 002/004/006 = 355/300/292，拒绝 0 | ✓ |

## 4. 测试与站外抽查

- 服务器 `python3 scripts/contract_tests.py`：**15/15 通过**（含 14 个接口形状与存档一致）；
- 服务器 `python3 -m unittest discover -s tests`：**30 个用例 OK**（Python 3.10.12，与生产同版本）；
- 站外（`http://81.71.14.93:18888`）实测：
  - `/api/surnames/李`：`coverage=in_corpus`，counts `total=7 / verified=7 / pending=0`，郡望 2、迁徙 1、最早书证 1、候选 3、语料审计 88 —— pending 不外发；
  - `/api/surnames/唐`：`coverage=not_in_corpus` 但同响应 `message=「已查到 2 条「唐」的记录，但都没有通过人工核验…」`
    —— B 报告的 coverage 语义矛盾**当场复现**（要 A 认档、C 改判据，见第 6 节）；
  - `/api/search?q=郡望`：0 命中（trigram 索引无两字 token）；`q=叔曼季`：2 命中 —— B 报告的两字检索问题**当场复现**；
  - `/api/surnames/慕容`：`not_in_corpus` +「库内既无主记录也无别名匹配」—— 文案正确。

## 5. 未通过项（1 项）与责任人

**`data/incoming/20261018-B/` 目录混入 `live-api-samples.json`、`stats-v2.json` 两份辅助 JSON**：
`validate_package.py` / `import_data.py` 目录模式会收下所有 `*.json`，于是整目录校验报 2 条错误
（「JSON 结构不是数组」「无法判断数据种类」，各带修复建议）。数据本身（4 个文件 355 条）不受影响，
已入库事实不受影响。

- 错误是否可读、可修复：**是**（错误指出文件与原因，修复=把辅助文件移进子目录或移出包目录）；
- 修复责任人：**成员 B**（文件在 B 的目录；C 不动别人的文件）；
- C 侧的防再犯：runbook 已写明「包目录里只放数据文件」（本次 PR）。

## 6. C 的处置（验收之外，B 的交接物里点名要 C 做的事）

| B 的提案 | C 的处置 | 依据 |
| --- | --- | --- |
| 补丁 A：不足三字回落 LIKE（`app/search.py`） | **采纳并已实现**：改 3 行 + 2 个单元测试 + 契约文档补一段；本地/服务器复测后部署 | 接口形状不变（`mode` 取值本就是 `fts5|like`），属实现路径修正，不需要 A 改契约 |
| 补丁 B：`data.origins` 容器（`app/queries.py`） | **采纳（同日裁决后实现）**：键名 `origins`，元素与 `commanderies` 同形；空壳响应同时补齐 `earliest_candidates`/`origins` | 裁决过程与实测见 §9 |
| 收编 `scripts/B/apply_review_status.py` | **采纳**：收入 `scripts/apply_review_status.py`（保持行为，评审注记改中性、加 `--operator` 兜底、路径改为 `scripts/`），补 7 个单元测试 + runbook/README 条目 | 补 `import_data.py` 缺的「改状态 + 写 review_logs」通道；收编前手工 UPDATE 会丢留痕 |
| `app/fts.py` 的 `rebuild()` 内部 commit | **采纳**：docstring 明确写出「本函数会 commit，不得放进预演事务」，runbook 同步 | 行为保持不变（文档级） |
| `coverage` 加 `queried_unverified` 档 | **采纳（同日裁决后实现）**：`publishable==0` 且（有 `pending` 或语料 `result_count>0`）即此档，两种子情况各有文案 | 裁决过程与实测见 §9 |
| `/api/stats`、roster 101、`data/incoming` 目录约定 | 记录在案，等 A 裁决 | 同上 |

## 7. 补丁 A 的独立复核（不采信 B 的结论，在现行库上自己跑）

同一份正式库副本、同一批查询，基线=现行 `app/`，打补丁=B 的演示副本（已核对只改了 2 个文件）：

| 查询 | 基线 | 打补丁 |
| --- | --- | --- |
| `郡望`（两字） | 0 | **18**（mode=like） |
| `邓氏`（两字） | 0 | **2** |
| `南阳`（两字） | 0 | **2** |
| `叔曼季`（三字） | 2（fts5） | 2（fts5，不受影响） |
| 14 姓 `other` 证据数 | 48 | 48（补丁 B 只在 overview 里多出 `origins` 键） |

演示副本（`data/tmp/b_patch_demo/`）与验证副本验收后已删除（B 在提案里授权可删）。

## 8. 结论

**验收通过**：数据包内容、库状态、导入留痕、契约测试、单元测试、站外可见性全部与 B 自述一致；
两字检索与 coverage 语义两处问题 C 侧当场复现。唯一遗留项（包目录混入辅助 JSON）错误可读可修复，
修复责任人 B。补丁 B 与 `coverage` 两处当日经 A 授权由 C 裁决并实现（§9）。

## 9. 同日裁决与落地（2026-10-18，经 A 授权、C 执行）

两项在验收当天下午拿到 A 的授权，按「先改契约文档、再改代码」的顺序落地：

1. **`data.origins`（键名裁决）**：取 `origins`——不在接口上暴露库内枚举值 `other`（备选 `other_evidences`
   会把这个词带进契约），元素与 `commanderies` 完全同形。实现：`app/queries.py` 增加
   `origins = evidence_rows(..., "other")` 与 `data.origins`；**空壳响应**（库里没这个姓）
   同时补齐 `earliest_candidates: []` 与 `origins: []`，六个证据容器键一个不少。
2. **`audit.coverage` 新档 `queried_unverified`**：判据 = `publishable == 0` 且（`pending > 0`
   或语料审计中存在 `result_count > 0`）；两种子情况文案分别为「已查到 N 条…未通过人工核验」
   与「已查询 N 部语料，其中 M 部报有相关记载线索」。实测影响面（裁决前）：101 个在册姓里
   **84 个**（仅有 pending）与 **3 个**（付/肖/闫：零证据行但语料有命中）此前都返回 `not_in_corpus`。
3. 契约文档（`docs/api-contract-v1.md`）第 1.1/2.2/5 节与顶部「裁决记录」已同步；
   契约存档 `surnames_overview.json`/`surnames_unknown.json` 由 `contract_tests.py` 重新归档，
   形状变化逐行可 diff；`check_overview` 增加对 `origins` 的断言、`check_restored_database`
   的 coverage 允许集补入新档（仍是 15/15）。
4. 测试：单元测试 44 个通过（新增 origins 同形、空壳键齐全、coverage 三档共 5 个）；
   ruff 全过。