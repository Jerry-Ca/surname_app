"""证据约束提示词（E 主责，任务 E-02）。

提示词的要求来自方案第 5.3 节与 docs/requirements.md：
只能依据提供的证据回答，不许补写书名、卷次、年代、地点、原文；
证据不足时必须回答“当前资料不足以确认”；
必须区分“文献明确记载 / 根据多条证据推测 / 当前语料库未查到”。
"""

from __future__ import annotations

ABSTAIN_TEXT = "当前资料不足以确认"

SYSTEM_PROMPT = """你只能根据提供的证据回答，不能补写书名、卷次、年代、地点和原文。
若证据不足，必须回答“当前资料不足以确认”。
必须区分三类表述：文献明确记载、根据多条证据推测、当前语料库未查到。
每个事实结论都要引用证据编号，格式为 [EV-XXX-000]。
不得使用证据之外的任何历史知识。""".strip()


def build_user_prompt(question: str, evidences: list[dict]) -> str:
    """把证据片段、来源与编号连同用户问题一起交给模型。

    每条证据必须包含：evidence_code、work_title、volume_or_section、
    original_excerpt、verification_status（见 api-contract.md 第 8 节）。
    提醒：只有 data/verified/ 中已核对的证据才允许进入这里。
    """
    raise NotImplementedError("E-02：实现证据片段拼装（当前接口仅定义形状，尚未接入模型）")


def render_abstain(reason: str) -> str:
    """证据不足或校验不通过时的固定回答文案，前端不要改写措辞。"""
    return ABSTAIN_TEXT
