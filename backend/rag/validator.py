"""回答校验（E 主责，任务 E-03）：证据编号约束。

规则（api-contract.md 第 8 节）：
  - 回答必须包含至少一个证据编号，且编号必须出现在本次检索结果中
  - 出现检索结果之外的新事实（书名、卷次、年代、地点）时判为不通过
  - 不通过时不得把原回答作为结论展示，改为“当前资料不足以确认”
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .prompts import ABSTAIN_TEXT

EVIDENCE_CODE = re.compile(r"\[(EV-[A-Z-]+-\d{3})\]")
# 模型自行补写书名的典型痕迹：书名号包裹的书名不在证据里
QUOTED_WORK = re.compile(r"《([^》]{1,40})》")


@dataclass
class ValidationResult:
    passed: bool
    answer: str
    citations: list[str]
    reason: str | None = None


def validate(answer: str, retrieved: list, allowed_work_titles: set[str] | None = None) -> ValidationResult:
    """校验回答是否被证据支撑。

    allowed_work_titles：本次检索结果中出现过的书名集合；
    回答里出现集合之外的书名即视为编造，直接判为不通过。
    """
    raise NotImplementedError("E-03：实现证据编号校验与未支撑内容拦截")


def abstain(reason: str) -> ValidationResult:
    return ValidationResult(passed=False, answer=ABSTAIN_TEXT, citations=[], reason=reason)
