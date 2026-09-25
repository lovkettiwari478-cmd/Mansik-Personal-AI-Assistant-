"""Activity (audit trail) + notifications endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from ..models import AuditLog, AuthSession, Notification, User, utcnow
from ..security.auth import get_db, require_auth

router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/activity")
def activity(
    category: str | None = None,
    limit: int = 100,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    limit = max(1, min(limit, 500))
    stmt = select(AuditLog).where(AuditLog.user_id == user.id)
    if category:
        stmt = stmt.where(AuditLog.category == category)
    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return {"activity": [
        {
            "id": a.id, "event_type": a.event_type, "category": a.category,
            "action": a.action, "resource": a.resource, "detail": a.detail,
            "ip": a.ip, "request_id": a.request_id, "created_at": a.created_at.isoformat(),
        } for a in rows
    ]}


@router.get("/notifications")
def notifications(
    unread_only: bool = False,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(100)
    rows = db.execute(stmt).scalars().all()
    unread_count = db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.read.is_(False)
        )
    ).scalar_one()
    return {
        "notifications": [
            {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body,
             "read": n.read, "created_at": n.created_at.isoformat()}
            for n in rows
        ],
        "unread": unread_count,
    }


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: str,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        from ..errors import NotFoundError
        raise NotFoundError("Notification not found.")
    n.read = True
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    rows = db.execute(
        select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))
    ).scalars().all()
    for n in rows:
        n.read = True
    db.commit()
    return {"ok": True, "marked": len(rows)}
