"""管理接口（契约第 9—10 节）：导入已核对数据、重建索引。

只允许 C 与 B 在服务器上调用：
  1. 必须携带 X-Admin-Token（值来自服务器环境变量 ADMIN_TOKEN）
  2. Nginx 层再按来源 IP 限制一次（见 deploy/nginx/surname_app.conf）
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..config import get_settings
from ..errors import ApiError, error_body

router = APIRouter(prefix="/admin", tags=["admin"])


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
    stage: str = "load"


class ReindexRequest(BaseModel):
    mode: str = Field("all", pattern="^(fulltext|vector|all)$")


def _not_implemented(what: str) -> ApiError:
    return ApiError(
        501,
        "NOT_IMPLEMENTED",
        f"{what}尚未实现（C-03 / C-05 未完成）。实现后请先跑 --dry-run 校验再正式导入。",
    )


@router.post("/import")
def import_data(payload: ImportRequest, x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> dict:
    _require_token(x_admin_token)
    raise _not_implemented("数据导入接口")


@router.post("/reindex")
def reindex(payload: ReindexRequest, x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> dict:
    _require_token(x_admin_token)
    raise _not_implemented("索引重建接口")


__all__ = ["router", "error_body"]
