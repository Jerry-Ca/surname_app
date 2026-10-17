"""管理接口（契约第 9—10 节）：导入已核对数据、重建索引。

只允许 C 与 B 在服务器上调用：
  1. 必须携带 X-Admin-Token（值来自服务器环境变量 ADMIN_TOKEN）
  2. Nginx 层再按来源 IP 限制一次（见 deploy/nginx/surname_app.conf）
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.session import get_db
from ..errors import ApiError, database_unavailable
from ..services import ingestion

router = APIRouter(prefix="/admin", tags=["admin"])

AdminToken = Annotated[str | None, Header(alias="X-Admin-Token")]


def _require_token(token: str | None) -> None:
    settings = get_settings()
    if not settings.admin_token:
        raise ApiError(401, "ADMIN_UNAUTHORIZED", "服务器未配置 ADMIN_TOKEN，管理接口不可用")
    if token != settings.admin_token:
        raise ApiError(401, "ADMIN_UNAUTHORIZED", "X-Admin-Token 缺失或不正确")


class ImportRequest(BaseModel):
    input_ref: str = Field(..., description="例如 data/verified/evidences.csv")
    dry_run: bool = True
    operator: str = Field(..., min_length=1, max_length=32)
    stage: str = Field("load", pattern="^(fetch|clean|verify|load|index)$")


class ReindexRequest(BaseModel):
    mode: str = Field("all", pattern="^(fulltext|vector|all)$")


@router.post("/import")
def admin_import(
    payload: ImportRequest,
    session: Annotated[Session, Depends(get_db)],
    x_admin_token: AdminToken = None,
) -> dict:
    """导入 data/verified/ 下的已核对数据；任一记录不通过则整体不写入。

    返回结构与错误行格式见 docs/api-contract.md 第 9 节。
    导入动作本身也写 ingestion_jobs（含 dry_run），B 交付时先用它验收。
    """
    _require_token(x_admin_token)
    try:
        outcome = ingestion.import_file(
            session,
            input_ref=payload.input_ref,
            operator=payload.operator,
            stage=payload.stage,
            dry_run=payload.dry_run,
        )
    except SQLAlchemyError as exc:
        # 契约第 1.2 节：数据库不可用是 503 DATABASE_UNAVAILABLE，不是 500
        raise database_unavailable(exc) from None
    return outcome.as_dict()


@router.post("/reindex")
def reindex(payload: ReindexRequest, x_admin_token: AdminToken = None) -> dict:
    _require_token(x_admin_token)
    raise ApiError(
        501,
        "NOT_IMPLEMENTED",
        "索引重建尚未实现（E-01 的检索与索引）。全文检索核对可用；向量索引缺失时按降级返回 skipped。",
    )
