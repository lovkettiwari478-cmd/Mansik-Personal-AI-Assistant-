"""Chat endpoints — SSE streaming orchestration + confirmation flow."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..ai.orchestrator import Orchestrator, execute_confirmed_action
from ..ai.providers import ProviderRegistry
from ..config import get_settings
from ..errors import AppError, NotFoundError, RateLimitError, ValidationAppError
from ..models import AuthSession, Confirmation, Conversation, Message, User, UserSettings, new_id, utcnow
from ..observability import get_logger, log
from ..security.auth import ensure_user_settings, get_db, require_auth
from ..security.rate_limit import limiter
from .schemas import ChatIn

logger = get_logger("mansik.chat")
router = APIRouter(prefix="/api", tags=["chat"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat")
async def chat(
    body: ChatIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    settings = get_settings()
    if settings.rate_limit_enabled:
        allowed, retry = limiter.hit(
            f"chat:{_client_ip(request)}", settings.rate_limit_chat_per_minute, 60
        )
        if not allowed:
            raise RateLimitError(f"Slow down a little — try again in {retry:.0f}s.")

    user, session = auth
    user_settings = ensure_user_settings(db, user.id)

    conversation = None
    if body.conversation_id:
        conversation = db.get(Conversation, body.conversation_id)
        if conversation is None or conversation.user_id != user.id:  # IDOR guard
            raise NotFoundError("Conversation not found.")
    else:
        conversation = Conversation(id=new_id(), user_id=user.id, title="New conversation")
        db.add(conversation)
        db.flush()

    text = body.message.strip()
    if not text:
        raise ValidationAppError("Message cannot be empty.")

    orchestrator = Orchestrator(db, ProviderRegistry.from_settings(settings))

    async def event_stream():
        try:
            async for event in orchestrator.handle(
                user=user, user_settings=user_settings, conversation=conversation,
                text=text, request_id=request.state.request_id, ip=_client_ip(request),
            ):
                yield _sse(event)
        except Exception as exc:  # stream errors must still be safe + visible
            log(logger, "error", "chat stream failed",
                error=f"{type(exc).__name__}: {exc}", user_id=user.id)
            yield _sse({"event": "error",
                        "message": "The assistant hit an unexpected error. It has been logged."})
            yield _sse({"event": "done", "message_id": None,
                        "conversation_id": conversation.id, "execution_summary": []})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering
            "Connection": "keep-alive",
        },
    )


# --------------------------------------------------------------------------
# Confirmations
# --------------------------------------------------------------------------

@router.get("/confirmations/pending")
def pending_confirmations(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    rows = db.execute(
        select(Confirmation).where(
            Confirmation.user_id == user.id, Confirmation.status == "pending",
            Confirmation.expires_at > utcnow(),
        ).order_by(Confirmation.created_at.desc()).limit(20)
    ).scalars().all()
    return {"confirmations": [_confirmation_json(c) for c in rows]}


@router.post("/confirmations/{confirmation_id}/approve")
async def approve_confirmation(
    confirmation_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    user_settings = ensure_user_settings(db, user.id)
    from ..permissions.firewall import PermissionFirewall

    firewall = PermissionFirewall(db)
    confirmation = firewall.approve_confirmation(
        user=user, confirmation_id=confirmation_id,
        request_id=request.state.request_id, ip=_client_ip(request),
    )

    # Emergency stop re-check at execution time
    if user_settings.emergency_stop:
        confirmation.status = "denied"
        confirmation.decided_at = utcnow()
        db.commit()
        raise ValidationAppError("Emergency stop is active — action not executed.")

    result = await execute_confirmed_action(
        db, user=user, user_settings=user_settings, confirmation=confirmation,
        request_id=request.state.request_id, ip=_client_ip(request),
    )

    # Persist continuation into the originating conversation, if any.
    if confirmation.conversation_id:
        conversation = db.get(Conversation, confirmation.conversation_id)
        if conversation is not None and conversation.user_id == user.id:
            db.add(Message(
                id=new_id(), conversation_id=conversation.id, user_id=user.id,
                role="assistant", content=result["continuation"], created_at=utcnow(),
                meta={
                    "mode": "confirmation_continuation",
                    "tools": [{"id": confirmation.tool_id, "success": result["success"],
                               "summary": result["summary"]}],
                    "confirmation": {"id": confirmation.id, "tool": confirmation.tool_id,
                                     "status": confirmation.status},
                },
            ))
            conversation.updated_at = utcnow()
            db.commit()
            result["conversation_id"] = conversation.id

    return {"result": result, "confirmation": _confirmation_json(confirmation)}


@router.post("/confirmations/{confirmation_id}/deny")
def deny_confirmation(
    confirmation_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    from ..permissions.firewall import PermissionFirewall
    firewall = PermissionFirewall(db)
    confirmation = firewall.deny_confirmation(
        user=user, confirmation_id=confirmation_id,
        request_id=request.state.request_id, ip=_client_ip(request),
    )
    db.commit()
    return {"confirmation": _confirmation_json(confirmation)}


def _confirmation_json(c: Confirmation) -> dict:
    return {
        "id": c.id, "tool_id": c.tool_id, "params": c.params, "risk": c.risk,
        "reason": c.reason, "status": c.status,
        "created_at": c.created_at.isoformat(), "expires_at": c.expires_at.isoformat(),
    }
