"""RAG 包（E 主责，任务 E-01 / E-02 / E-03 / E-04）。

边界：不改表结构、不写数据库、不暴露给前端直接调用模型。
契约：输入是检索到的证据片段（含 evidence_code），输出必须能映射到
docs/api-contract.md 第 8 节的 citations / answer_mode / abstained。
"""
