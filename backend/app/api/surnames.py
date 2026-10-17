"""姓氏查询接口（契约第 4—7 节，另含语料审计）。

路由层只做参数校验、错误映射与响应头；取数与拼装全部在 app/services/queries.py，
这样 E 的 RAG 检索能复用同一套匹配与拼装逻辑，不会出现第二套实现。
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..errors import ApiError
from ..services import queries

router = APIRouter(tags=["surnames"])

SURNAME_PATTERN = re.compile(r"^[\u4e00-\u9fff]{1,8}$")

# 契约第 1 节：结构化查询接口返回 Cache-Control: public, max-age=60
CACHE_CONTROL = "public, max-age=60"


def _validate_surname(name: str) -> str:
    candidate = (name or "").strip()
    if not candidate:
        raise ApiError(400, "INVALID_SURNAME_INPUT", "姓氏输入无效：不能为空", {"reason": "empty"})
    if not SURNAME_PATTERN.match(candidate):
        raise ApiError(
            400,
            "INVALID_SURNAME_INPUT",
            "姓氏输入无效：仅支持 1—8 个汉字",
            {"input": name, "reason": "not_chinese_or_too_long"},
        )
    return candidate


def _respond(response: Response, handler, *args, **kwargs) -> dict:
    """统一处理数据库不可用与缓存头，避免每个路由重复一遍。"""
    try:
        body = handler(*args, **kwargs)
    except SQLAlchemyError as exc:
        # 契约第 1.2 节：数据库不可用返回 503 DATABASE_UNAVAILABLE（健康检查同时报 connected=false）
        raise ApiError(
            503,
            "DATABASE_UNAVAILABLE",
            "数据库不可用，结构化查询暂时无法完成；请稍后重试，或用 /api/health 确认状态",
            {"reason": str(exc)[:200]},
        ) from None
    response.headers["Cache-Control"] = CACHE_CONTROL
    return body


SessionDep = Annotated[Session, Depends(get_db)]


@router.get("/surnames/{name}")
def surname_overview(name: str, response: Response, session: SessionDep) -> dict:
    candidate = _validate_surname(name)
    return _respond(response, queries.overview, session, candidate)


@router.get("/surnames/{name}/earliest")
def surname_earliest(name: str, response: Response, session: SessionDep) -> dict:
    candidate = _validate_surname(name)
    return _respond(response, queries.earliest, session, candidate)


@router.get("/surnames/{name}/commanderies")
def surname_commanderies(
    name: str,
    response: Response,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    candidate = _validate_surname(name)
    return _respond(response, queries.commanderies, session, candidate, page, page_size)


@router.get("/surnames/{name}/migrations")
def surname_migrations(
    name: str,
    response: Response,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    candidate = _validate_surname(name)
    return _respond(response, queries.migrations, session, candidate, page, page_size)


@router.get("/surnames/{name}/corpus-checks")
def surname_corpus_checks(
    name: str,
    response: Response,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    candidate = _validate_surname(name)
    return _respond(response, queries.corpus_checks, session, candidate, page, page_size)
