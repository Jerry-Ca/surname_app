"""搜索服务（C-04 落地姓氏匹配，C-05 续做证据全文检索）。

职责：
  1. 输入标准化：全角/半角、空白、标点、大小写在查询前统一
  2. 姓氏解析：主记录精确匹配 → 别名/繁简异体匹配 → 未命中
  3. 证据全文检索：匹配 + 排序 + 分页，返回带证据编号与来源信息的结果

设计取舍：
  - 繁简与异体**不写死在代码里**，只认 `surname_aliases` 表里的数据。
    字形映射一旦硬编码，就等于后端替 B 宣布“某字与某字同源”，必须有据可查（铁律 1）。
  - 全文检索以 **LIKE 基线 + PostgreSQL pg_trgm 增强**实现：pg_trgm 未安装或查询失败时
    自动回落 LIKE，并在 `SearchPage.degraded` 里说明走了哪条路径（降级矩阵要求可观测）。
    不用 PostgreSQL 默认 FTS 配置：它按空白切词，中文长句会被当成一个词，实测不可用。
  - 排序结果必须**可解释、可复现**：先看状态（已核对优先），再看命中位置（结论 > 原文 > 卷次），
    最后按年份、编号收敛，不用相似度黑盒决定展示顺序。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import func, literal, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import Evidence, Surname, SurnameAlias
from .serializers import evidence_summary

# 允许出现在输入里的分隔与标点（查询前一律去掉，不参与匹配）
_NOISE = re.compile(r"[\s　·・.,，。/、\\|()（）\[\]【】\"'“”‘’]+")

# 别名类型 → 契约第 2.3 节的 match_type
_ALIAS_MATCH_TYPE = {
    "variant": "variant",
    "traditional_simplified": "variant",
    "honorific": "alias",
    "other": "alias",
}

# 检索可见的状态（与 queries.py 一致：pending 不外发）
SEARCHABLE_STATUSES = ("verified", "disputed", "link_stale", "retracted")

_STATUS_PRIORITY = {"verified": 0, "disputed": 1, "link_stale": 2, "retracted": 3}

# 命中位置的优先级：事实结论 > 原文摘录 > 卷次
_FIELD_PRIORITY = {"claim_text": 0, "original_excerpt": 1, "volume_or_section": 2}

SNIPPET_RADIUS = 24
MAX_PAGE_SIZE = 100


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
    if alias is None:
        # 别名表里可能存了带括号/空白的写法：用首字缩小范围后，再按同一套归一化比较一次
        alias = next(
            (
                record
                for record in session.scalars(
                    select(SurnameAlias).where(SurnameAlias.alias_name.like(f"{candidate[0]}%"))
                )
                if normalize_input(record.alias_name) == candidate
            ),
            None,
        )
    if alias is not None:
        return SurnameMatch(
            alias.surname,
            candidate,
            _ALIAS_MATCH_TYPE.get(alias.alias_type, "alias"),
            alias_type=alias.alias_type,
        )

    return SurnameMatch(None, candidate, "none")


# ---------------------------------------------------------------- 全文检索


def dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""


def supports_trigram(session: Session) -> bool:
    """PostgreSQL 且装了 pg_trgm 扩展时返回 True；其余（含 SQLite）返回 False。

    探不到就回落 LIKE：检索能力缺失不允许让查询失败（降级矩阵）。
    """
    if dialect_name(session) != "postgresql":
        return False
    try:
        return bool(session.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'")))
    except SQLAlchemyError:
        return False


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _snippet(hit_text: str, query: str) -> str | None:
    """取命中位置前后的一小段**原文子串**（不生成、不改写），便于前端高亮。"""
    position = hit_text.find(query)
    if position < 0:
        return None
    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(hit_text), position + len(query) + SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(hit_text) else ""
    return f"{prefix}{hit_text[start:end]}{suffix}"


def _matched_field(evidence: Evidence, query: str) -> str:
    for column in ("claim_text", "original_excerpt", "volume_or_section"):
        if query in getattr(evidence, column):
            return column
    return "claim_text"


@dataclass
class SearchHit:
    """一条命中记录。

    保留 ORM 对象是为了让 E-01 能直接拿到 `evidence.id`（向量检索要对齐同一条记录）；
    对外序列化只走 `serializers.evidence_summary`，不把数据库自增 id 交给前端。
    `matched_field` 与 `snippet` 暂不进 JSON：契约里还没有这两个字段，
    等 A 把它们写进 docs/api-contract.md 再暴露（先改文档再改代码）。
    """

    evidence: Evidence
    matched_field: str
    snippet: str | None = None

    @property
    def evidence_id(self) -> int:
        return self.evidence.id

    @property
    def evidence_code(self) -> str:
        return self.evidence.evidence_code

    def as_summary(self) -> dict:
        return evidence_summary(self.evidence)


@dataclass
class SearchPage:
    items: list[SearchHit]
    page: int
    page_size: int
    total: int
    has_more: bool
    query: str
    degraded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """给调用方的稳定 JSON：分页字段与契约 2.5 节一致，其余不塞临时字段。"""
        return {
            "query": self.query,
            "items": [hit.as_summary() for hit in self.items],
            "pagination": {
                "page": self.page,
                "page_size": self.page_size,
                "total": self.total,
                "has_more": self.has_more,
            },
            "degraded": self.degraded,
        }


def _validate_page(page: int, page_size: int) -> None:
    if page < 1:
        raise ApiError(422, "VALIDATION_ERROR", "page 必须 >= 1", {"field": "page", "value": page})
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"page_size 必须在 1—{MAX_PAGE_SIZE} 之间",
            {"field": "page_size", "value": page_size},
        )


def search_evidences(
    session: Session,
    query: str,
    *,
    surname: Surname | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SearchPage:
    """在证据的结论 / 原文摘录 / 卷次里检索，返回排序后的分页结果。

    - 查询词为空或只有标点：422 VALIDATION_ERROR（契约 1.2 节的统一错误结构）
    - `pending` 不参与检索（data-dictionary.md 第 7 节）
    - 结果带 `evidence_id`（E-01 的向量检索要对齐同一条记录）与来源信息
    """
    _validate_page(page, page_size)
    normalized = normalize_input(query)
    if not normalized:
        raise ApiError(422, "VALIDATION_ERROR", "查询词不能为空（去掉空白与标点后为空）", {"field": "query"})

    pattern = _like_pattern(normalized)
    match_clause = or_(
        Evidence.claim_text.ilike(pattern, escape="\\"),
        Evidence.original_excerpt.ilike(pattern, escape="\\"),
        Evidence.volume_or_section.ilike(pattern, escape="\\"),
    )
    conditions = [Evidence.verification_status.in_(SEARCHABLE_STATUSES), match_clause]
    if surname is not None:
        conditions.append(Evidence.surname_id == surname.id)

    total = session.scalar(select(func.count(Evidence.id)).where(*conditions)) or 0

    statement = select(Evidence).where(*conditions)
    degraded: list[str] = []
    if supports_trigram(session):
        # pg_trgm 可用：让数据库按相似度先排一次（数据量大时这一步很关键）
        try:
            similarity = func.word_similarity(literal(normalized), Evidence.claim_text)
            rows = list(session.scalars(statement.order_by(similarity.desc())))
        except SQLAlchemyError:
            degraded.append("trigram_query_failed_like_fallback")
            rows = list(session.scalars(statement))
    else:
        # 明确记录当前走的是 LIKE 基线（SQLite 本地/测试，或 PostgreSQL 未装 pg_trgm）
        degraded.append("fulltext_like_fallback")
        rows = list(session.scalars(statement))

    def sort_key(evidence: Evidence) -> tuple:
        return (
            _STATUS_PRIORITY.get(evidence.verification_status, 9),
            _FIELD_PRIORITY[_matched_field(evidence, normalized)],
            1 if evidence.year_start is None else 0,
            evidence.year_start if evidence.year_start is not None else 0,
            evidence.evidence_code,
        )

    rows.sort(key=sort_key)
    start = (page - 1) * page_size
    window = rows[start : start + page_size]

    items = [
        SearchHit(
            evidence=evidence,
            matched_field=_matched_field(evidence, normalized),
            snippet=_snippet(evidence.original_excerpt, normalized) or _snippet(evidence.claim_text, normalized),
        )
        for evidence in window
    ]

    return SearchPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_more=page * page_size < total,
        query=normalized,
        degraded=degraded,
    )
