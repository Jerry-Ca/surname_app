"""健康检查（契约第 3 节）：本地自检、服务器健康检查、部署脚本都依赖它。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response

from ..config import get_settings
from ..db.session import check_database

router = APIRouter(tags=["health"])


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/health")
def health(response: Response) -> dict:
    settings = get_settings()
    database = check_database()

    degraded: list[str] = []
    if not settings.model_configured:
        degraded.append("model_unavailable")
    if not settings.embedding_configured:
        degraded.append("embedding_unavailable")
    if not database["connected"]:
        degraded.append("database_unavailable")

    status = "ok"
    if not database["connected"]:
        status = "down"
    elif degraded:
        status = "degraded"

    payload = {
        "status": status,
        "api_version": settings.api_version,
        "git_sha": None,  # 部署时由 CI 或服务器注入；本地为 null
        "database": {
            "connected": database["connected"],
            "dialect": database["dialect"],
            "migration_revision": database["migration_revision"],
        },
        "model": {
            "configured": settings.model_configured,
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "embedding_configured": settings.embedding_configured,
        },
        "degraded": degraded,
        "checked_at": _now(),
    }
    if not database["connected"] and database.get("error"):
        payload["database"]["error"] = database["error"]

    # 数据库不可用时返回 503，但仍返回完整健康报告（便于定位问题）
    if status == "down":
        response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    return payload
