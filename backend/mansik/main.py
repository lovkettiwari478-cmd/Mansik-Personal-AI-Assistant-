"""MANISK application factory & entrypoint.

Production:  uvicorn mansik.main:app --host 0.0.0.0 --port 8000
Development: MANISK_ENVIRONMENT=development + `vite dev` (proxy /api)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .database import get_engine
from .errors import AppError, app_error_handler, unhandled_error_handler, validation_error_handler
from .migrations import run_migrations
from .observability import configure_logging, get_logger, log
from .security.middleware import (
    ExecutionTraceMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware,
)

logger = get_logger("mansik.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log(logger, "info", "MANISK starting",
        version=__version__, environment=settings.environment)
    run_migrations()
    if settings.scheduler_enabled:
        from .workers.scheduler import start_scheduler
        start_scheduler(settings.scheduler_interval_seconds)
    yield
    from .workers.scheduler import stop_scheduler
    stop_scheduler
    log(logger, "info", "MANISK stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MANISK",
        version=__version__,
        description="Personal AI Operating System",
        docs_url="/api/docs" if settings.is_dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.is_dev else None,
        lifespan=lifespan,
    )

    # middleware order: outermost first added
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ExecutionTraceMiddleware)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    from .api import (
        activity, auth, automations, calendar, chat, conversations, files,
        memories, security, settings as settings_api, status, tasks,
    )
    app.include_router(status.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(memories.router)
    app.include_router(tasks.router)
    app.include_router(calendar.router)
    app.include_router(automations.router)
    app.include_router(files.router)
    app.include_router(activity.router)
    app.include_router(security.router)
    app.include_router(settings_api.router)

    @app.get("/api/ready")
    def ready():
        return {"ok": True}

    # ---- frontend (built SPA served from the same origin) -------------------
    dist = settings.frontend_dist
    if dist and os.path.isdir(dist):
        assets = os.path.join(dist, "assets")
        if os.path.isdir(assets):
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str, request: Request):
            # never swallow API paths
            if full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"error": {"code": "not_found", "message": "Unknown API route."}},
                )
            if full_path.startswith("storage/"):
                return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
            candidate = os.path.normpath(os.path.join(dist, full_path))
            if (candidate.startswith(os.path.abspath(dist))
                    and os.path.isfile(candidate)
                    and ".." not in full_path
                    and not full_path.startswith("api")):
                return FileResponse(candidate)
            return FileResponse(os.path.join(dist, "index.html"))

        log(logger, "info", "serving frontend", dist=dist)
    else:
        @app.get("/", include_in_schema=False)
        async def root():
            return JSONResponse({
                "app": "MANISK",
                "version": __version__,
                "status": "api-only (no frontend build found)",
                "health": "/api/health",
            })

    return app


app = create_app()
