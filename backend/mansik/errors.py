"""Application errors and safe exception handling.

Users never see raw stack traces: unhandled exceptions become generic 500s
with a request id they can quote; details go to structured logs only.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .observability import get_logger, log, request_id_var

logger = get_logger("mansik.errors")


class AppError(Exception):
    """Base for expected, user-safe errors."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.detail = detail or {}


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"


def _json(status: int, code: str, message: str, request_id: str, extra: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    if extra:
        body["error"].update(extra)
    return JSONResponse(status_code=status, content=body)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return _json(exc.status_code, exc.code, exc.message, request_id_var.get(), exc.detail or None)


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return _json(422, "validation_error", "Invalid request payload.", request_id_var.get())


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_var.get()
    log(logger, "error", "unhandled exception",
        path=request.url.path, method=request.method,
        exception=f"{type(exc).__name__}: {exc}")
    logger.exception("unhandled_exception")
    return _json(
        500, "internal_error",
        "Something went wrong on our side. The error was logged — quote the request id if you report it.",
        request_id,
    )
