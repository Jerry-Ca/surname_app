"""检索排序（E 主责，任务 E-01）：精确匹配 + 全文检索 + 向量检索。

排序规则（docs/data-dictionary.md 与 api-contract.md）：
  1. 已核对（verified）优先，其次 link_stale / disputed，retracted 不参与结论
  2. 有出处（source_url 或 access_note）优先
  3. 争议内容保留并标记，不得因为分数低而丢弃
  4. 每条结果必须带 evidence_code，供回答校验使用
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetrievedEvidence:
    evidence_code: str
    claim_text: str
    original_excerpt: str
    work_title: str
    volume_or_section: str
    verification_status: str
    confidence: str
    source_url: str | None = None
    score: float = 0.0
    matched_by: list[str] = field(default_factory=list)


def retrieve(surname: str, question: str, top_k: int = 8) -> list[RetrievedEvidence]:
    """返回排序后的证据列表；向量不可用时自动退化为精确匹配 + 全文检索。"""
    raise NotImplementedError("E-01：实现检索排序（依赖 C-05 的搜索服务）")
