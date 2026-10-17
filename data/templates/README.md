# 数据模板说明

本目录只放**表头模板**，用来保证 B 导出的 CSV 列名与 [../../docs/data-dictionary.md](../../docs/data-dictionary.md) 完全一致。

## 用法

```bash
# 复制模板再填内容，不要直接改模板文件
cp data/templates/evidences.csv data/verified/evidences.csv
cp data/templates/migrations.csv data/verified/migrations.csv
```

## 硬性约定

1. **列名不得改动、不得翻译、不得调整顺序**（顺序不影响校验，但保持一致便于人工比对）。
2. 一行 = 一条原子证据。多条证据不要挤在一格里。
3. 年份用整数，公元前为负；不确定就留空，改填 `time_label`。
4. `verification_status` 只允许 `verified` / `disputed` / `link_stale` / `retracted`（`pending` 的记录只能留在 `data/raw/`）。
5. 编码推荐 UTF-8 with BOM（Excel 双击打开不乱码）；`scripts/validate_data.py` 对有无 BOM 都兼容。
6. 提交前先自检：`python scripts/validate_data.py --path data`。

## 示例行（**占位，不得作为真实数据使用**）

下面这行只为说明“字段怎么填”，其书名、卷次、摘录均为占位符。
**任何编造的书名、卷次、年代、原文都不得进入 `data/verified/`**（[../../AGENTS.md](../../AGENTS.md) 铁律 1）。

```csv
evidence_code,surname,evidence_type,claim_text,work_title,work_author,dynasty,volume_or_section,page_or_location,original_excerpt,source_code,source_url,access_note,accessed_at,verification_status,confidence,verified_by,verification_note,dispute_group,year_start,year_end,time_label
EV-LI-001,李,earliest_attestation,<一句话事实结论，须与原文一致>,<真实书名>,<作者或佚名>,<朝代>,<卷次或篇章>,<页码或定位>,<回看原文后的短摘录，禁止改写>,SRC-001,<来源链接>,<无链接时说明原因，如纸本>,2026-10-17T03:21:00Z,verified,high,B,<核对了什么、何处存疑>,,-100,,<原文的时间表述>
```

`validate_data.py` 会把含 `<...>`、`示例`、`待填` 等占位标记的记录在 `data/verified/` 中判为错误——这正是我们希望的：占位符不能混进正式数据。