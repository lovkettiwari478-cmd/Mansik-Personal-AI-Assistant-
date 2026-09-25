"""Security + observability middleware.

- RequestIDMiddleware: assigns a request id, binds it to logs, adds the
  ``X-Request-ID`` response header.
- SecurityHeadersMiddleware: standard hardening headers (CSP allows the
  same-origin API and inline styles for the bundled SPA; nothing external).
"""

from __future__ import annotations

import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..observability import execution_id_var, get_logger, log, request_id_var

logger = get_logger("mansik.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or secrets.token_hex(8)
        token = request_id_var.set(rid)
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        if not request.url.path.startswith("/api/health"):
            log(logger, "info", "request",
                method=request.method, path=request.url.path,
                status=response.status_code, duration_ms=duration_ms)
        return response


class ExecutionTraceMiddleware(BaseHTTPMiddleware):
    """Binds an execution id for chat/tool executions, exposed in responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        eid = secrets.token_hex(8)
        token = execution_id_var.set(eid)
        try:
            response = await call_next(request)
        finally:
            execution_id_var.reset(token)
        response.headers["X-Execution-ID"] = eid
        return response


CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response
