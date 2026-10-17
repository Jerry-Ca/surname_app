"""证据问答（契约第 8 节）。E 主责：backend/rag/。

未接入模型时也必须返回 200 与降级标记，绝不返回 5xx——
结构化证据查询不受影响，这是验收第 7 项的要求。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["ask"])

ABSTAIN_TEXT = "当前资料不足以确认"


class AskRequest(BaseModel):
    surname: str = Field(..., max_length=8)
    question: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(8, ge=1, le=20)


@router.post("/ask")
def ask(payload: AskRequest) -> dict:
    # TODO E-03/E-04：接入检索、提示词与回答校验；当前为明确的降级响应
    return {
        "answer": ABSTAIN_TEXT,
        "answer_mode": "degraded_no_model",
        "abstained": True,
        "abstain_reason": "model_unavailable",
        "citations": [],
        "retrieved_count": 0,
        "model": {"provider": "deepseek", "model": None, "latency_ms": None},
        "notice": "智能摘要尚未接入（E-03 / E-04 未完成）；结构化证据查询正常可用。",
    }
