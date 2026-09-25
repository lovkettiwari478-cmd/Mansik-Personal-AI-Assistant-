"""Conversations (short-term memory management)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..errors import NotFoundError
from ..models import AuthSession, Conversation, Message, User, utcnow
from ..security.auth import get_db, require_auth

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_conversations(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    rows = db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.archived.is_(False))
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    ).scalars().all()
    return {"conversations": [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat(),
         "updated_at": c.updated_at.isoformat()} for c in rows
    ]}


@router.post("", status_code=201)
def create_conversation(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    from ..models import new_id
    convo = Conversation(id=new_id(), user_id=user.id, title="New conversation")
    db.add(convo)
    db.commit()
    return {"conversation": {"id": convo.id, "title": convo.title}}


@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    convo = db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        raise NotFoundError("Conversation not found.")
    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
        .limit(500)
    ).scalars().all()
    return {"messages": [
        {
            "id": m.id, "role": m.role, "content": m.content, "meta": m.meta,
            "created_at": m.created_at.isoformat(),
        } for m in rows
    ]}


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    convo = db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        raise NotFoundError("Conversation not found.")
    db.delete(convo)  # messages cascade
    db.commit()
    return {"ok": True}
