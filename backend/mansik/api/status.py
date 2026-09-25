"""Health + status + integrations + tool catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..config import get_settings
from ..database import get_engine
from ..models import AuthSession, User
from ..security.auth import get_db, require_auth
from ..tools import ToolContext, registry as tool_registry

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/health")
def health():
    """Liveness + dependency check (no auth, no details leaked)."""
    db_ok = True
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    status = "ok" if db_ok else "degraded"
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={"status": status, "database": db_ok, "version": get_settings().version},
    )


@router.get("/status")
def status(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db=Depends(get_db),
):
    user, session = auth
    settings = get_settings()
    return settings.public_status()


@router.get("/tools")
def tools(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db=Depends(get_db),
):
    user, _ = auth
    from ..security.auth import ensure_user_settings
    user_settings = ensure_user_settings(db, user.id)
    ctx = ToolContext(db=db, user=user, user_settings=user_settings)
    return {"tools": [tool_registry.describe(t, ctx) for t in tool_registry.all()]}


@router.get("/integrations")
def integrations(
    auth: tuple[User, AuthSession] = Depends(require_auth),
):
    """Honest integration status: configured via env vars only. No fake
    connected-states; credentials are never returned."""
    settings = get_settings()
    return {"integrations": [
        {
            "id": "ai-provider",
            "name": "AI model provider",
            "description": "Any OpenAI-compatible API (NVIDIA NIM/Nemotron, OpenAI, Groq, Together, Ollama, vLLM, LM Studio).",
            "configured": bool(settings.ai_base_url and settings.ai_model),
            "required_env": ["MANISK_AI_BASE_URL", "MANISK_AI_MODEL", "MANISK_AI_API_KEY (if the provider requires one)"],
        },
        {
            "id": "web-search",
            "name": "Web search",
            "description": "Tavily API (preferred) or keyless DuckDuckGo fallback.",
            "configured": bool(settings.tavily_api_key) or settings.allow_duckduckgo_search,
            "required_env": ["MANISK_TAVILY_API_KEY (optional; DuckDuckGo fallback is on by default)"],
        },
        {
            "id": "email",
            "name": "Email (SMTP)",
            "description": "Outbound email for the email.send tool.",
            "configured": bool(settings.smtp_host and settings.smtp_from),
            "required_env": ["MANISK_SMTP_HOST", "MANISK_SMTP_PORT", "MANISK_SMTP_USER",
                             "MANISK_SMTP_PASSWORD", "MANISK_SMTP_FROM"],
        },
    ]}
