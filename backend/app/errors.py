"""统一错误返回结构（docs/api-contract.md 第 1.2 节）。

任何新增错误码都必须先写进 api-contract.md，再在这里使用。
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict | None = None, request_id: str | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id or f"req_{uuid.uuid4().hex[:12]}",
        }
    }


def database_unavailable(exc: Exception) -> ApiError:
    """把数据库异常映射成契约第 1.2 节的 503 DATABASE_UNAVAILABLE。

    查询接口与管理接口都用这一个入口：探测发现管理接口此前没做映射，
    数据库不可用时返回的是 500 INTERNAL_ERROR，与契约不符。
    """
    return ApiError(
        503,
        "DATABASE_UNAVAILABLE",
        "数据库不可用，操作暂时无法完成；请稍后重试，或用 /api/health 确认状态",
        {"reason": str(exc)[:200]},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 契约第 1.2 节：路径不存在必须是 404 + ENDPOINT_NOT_FOUND，不能是 FastAPI 默认的 {"detail": ...}
        if exc.status_code == 404:
            body = error_body("ENDPOINT_NOT_FOUND", "请求的接口不存在", {"path": exc.detail})
        else:
            body = error_body(f"HTTP_{exc.status_code}", str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=body, headers={"Cache-Control": "no-store"})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body("VALIDATION_ERROR", "请求参数校验失败", {"errors": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "服务内部错误，请把 request_id 提供给 C 或 E 排查"),
        )
