"""搜索服务（C-04 落地姓氏匹配，C-05 续做证据全文检索）。

职责：
  1. 输入标准化：全角/半角、空白、标点、大小写在查询前统一
  2. 姓氏解析：主记录精确匹配 → 别名/繁简异体匹配 → 未命中
  3.（C-05）证据全文检索与排序

设计取舍：繁简与异体**不写死在代码里**，只认 `surname_aliases` 表里的数据。
理由：字形映射表一旦硬编码，就等于后端替 B 宣布“某字与某字同源”，
这类判断必须有据可查（AGENTS.md 铁律 1）。别名由 B 在数据里登记。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Surname, SurnameAlias

# 允许出现在输入里的分隔与标点（查询前一律去掉，不参与匹配）
_NOISE = re.compile(r"[\s　·・.,，。/、\\|()（）\[\]【】\"'“”‘’]+")

# 别名类型 → 契约第 2.3 节的 match_type
_ALIAS_MATCH_TYPE = {
    "variant": "variant",
    "traditional_simplified": "variant",
    "honorific": "alias",
    "other": "alias",
}


def normalize_input(text: str | None) -> str:
    """查询词标准化：NFKC（全角→半角）+ 去空白与分隔标点。

    注意这里**不改字形**：繁简与异体靠 surname_aliases 匹配，不靠转换规则。
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return _NOISE.sub("", normalized).strip()


@dataclass
class SurnameMatch:
    surname: Surname | None
    matched_input: str
    match_type: str  # exact / alias / variant / compound / none
    alias_type: str | None = None


def resolve_surname(session: Session, raw_input: str) -> SurnameMatch:
    """把用户输入解析成姓氏主记录，并说明匹配方式。"""
    candidate = normalize_input(raw_input)
    if not candidate:
        return SurnameMatch(None, candidate, "none")

    surname = session.scalar(select(Surname).where(Surname.canonical_name == candidate))
    if surname is not None:
        match_type = "compound" if surname.category == "compound" else "exact"
        return SurnameMatch(surname, candidate, match_type)

    alias = session.scalar(select(SurnameAlias).where(SurnameAlias.alias_name == candidate))
    if alias is not None:
        return SurnameMatch(
            alias.surname,
            candidate,
            _ALIAS_MATCH_TYPE.get(alias.alias_type, "alias"),
            alias_type=alias.alias_type,
        )

    return SurnameMatch(None, candidate, "none")
