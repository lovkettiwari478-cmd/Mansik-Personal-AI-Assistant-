"""Memory management endpoints — full user control over long-term memory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..errors import NotFoundError, ValidationAppError
from ..memory.service import search_memories
from ..models import AuthSession, Memory, User, new_id, utcnow
from ..observability import audit
from ..security.auth import get_db, require_auth
from .schemas import MemoryIn, MemoryPatch, MemorySearchIn

router = APIRouter(prefix="/api/memories", tags=["memory"])


def _memory_json(m: Memory) -> dict:
    return {
        "id": m.id, "kind": m.kind, "content": m.content, "importance": m.importance,
        "source": m.source, "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
    }


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


def _own_memory(db: DbSession, user: User, memory_id: str) -> Memory:
    m = db.get(Memory, memory_id)
    if m is None or m.user_id != user.id or m.deleted_at is not None:
        raise NotFoundError("Memory not found.")
    return m


@router.get("")
def list_memories(
    kind: str | None = None,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    stmt = select(Memory).where(Memory.user_id == user.id, Memory.deleted_at.is_(None))
    if kind:
        stmt = stmt.where(Memory.kind == kind)
    stmt = stmt.order_by(Memory.updated_at.desc()).limit(500)
    rows = db.execute(stmt).scalars().all()
    return {"memories": [_memory_json(m) for m in rows], "count": len(rows)}


@router.post("", status_code=201)
def create_memory(
    body: MemoryIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    lowered = body.content.lower()
    if any(s in lowered for s in ("password", "api key", "secret key", "private key")):
        raise ValidationAppError("This looks like it may contain credentials — refused.")
    m = Memory(
        id=new_id(), user_id=user.id, kind=body.kind, content=body.content.strip(),
        importance=body.importance, source="explicit", created_at=utcnow(), updated_at=utcnow(),
    )
    db.add(m)
    audit(db, event_type="memory_created", category="memory", action="Memory created",
          user_id=user.id, resource=m.id, ip=_client_ip(request),
          request_id=request.state.request_id)
    db.commit()
    return {"memory": _memory_json(m)}


@router.patch("/{memory_id}")
def update_memory(
    memory_id: str, body: MemoryPatch, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    m = _own_memory(db, user, memory_id)
    if body.content is not None:
        m.content = body.content.strip()
    if body.kind is not None:
        m.kind = body.kind
    if body.importance is not None:
        m.importance = body.importance
    m.updated_at = utcnow()
    audit(db, event_type="memory_updated", category="memory", action="Memory updated",
          user_id=user.id, resource=m.id, ip=_client_ip(request),
          request_id=request.state.request_id)
    db.commit()
    return {"memory": _memory_json(m)}


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    m = _own_memory(db, user, memory_id)
    m.deleted_at = utcnow()
    audit(db, event_type="memory_deleted", category="memory", action="Memory deleted",
          user_id=user.id, resource=m.id, ip=_client_ip(request),
          request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


@router.post("/search")
def search(
    body: MemorySearchIn,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    results = search_memories(db, user.id, body.query, limit=body.limit)
    return {"memories": [_memory_json(m) for m in results], "count": len(results)}
