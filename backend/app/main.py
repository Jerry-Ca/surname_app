"""FastAPI 应用入口。

启动：uvicorn app.main:app --reload --port 8000（在 backend/ 目录下执行）
接口契约：../docs/api-contract.md
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, ask, health, surnames
from .config import get_settings
from .errors import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="姓氏郡望与家族迁徙寻根系统 API",
        version=settings.api_version,
        description="证据优先的姓氏研究工具：最早书证、郡望、迁徙线索与语料审计。字段以 docs/api-contract.md 为准。",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    register_exception_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(surnames.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    # 同源部署时不需要 CORS；只有本地前后端分离调试时才填 CORS_ORIGINS
    if settings.cors_origin_list and not settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": "surname_app",
            "api_version": settings.api_version,
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
