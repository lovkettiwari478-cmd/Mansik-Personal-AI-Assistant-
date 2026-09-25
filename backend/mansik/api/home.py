"""Home summary — one round-trip for the command center.

Every number comes from the user's real data. No fake statistics.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..models import (
    Automation, AuthSession, Confirmation, Event, Memory, Notification,
    Task, User, AuditLog, utcnow,
)
from ..security.auth import ensure_user_settings, get_db, require_auth

router = APIRouter(prefix="/api/home", tags=["home"])


@router.get("/summary")
def home_summary(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    settings = ensure_user_settings(db, user.id)
    now = utcnow()

    # user's "today" boundaries in their timezone
    try:
        tz = ZoneInfo(settings.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = now.astimezone(tz)
    local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_utc = local_day_start.astimezone(ZoneInfo("UTC"))
    day_end_utc = day_start_utc + timedelta(days=1)

    # tasks
    open_tasks = db.execute(
        select(func.count()).select_from(Task).where(
            Task.user_id == user.id, Task.deleted_at.is_(None),
            Task.status.in_(["todo", "in_progress"]),
        )
    ).scalar_one()
    due_today = db.execute(
        select(func.count()).select_from(Task).where(
            Task.user_id == user.id, Task.deleted_at.is_(None),
            Task.status.in_(["todo", "in_progress"]),
            Task.due_at >= day_start_utc, Task.due_at < day_end_utc,
        )
    ).scalar_one()
    overdue = db.execute(
        select(func.count()).select_from(Task).where(
            Task.user_id == user.id, Task.deleted_at.is_(None),
            Task.status.in_(["todo", "in_progress"]),
            Task.due_at < now,
        )
    ).scalar_one()
    next_tasks = db.execute(
        select(Task).where(
            Task.user_id == user.id, Task.deleted_at.is_(None),
            Task.status.in_(["todo", "in_progress"]),
        ).order_by(Task.due_at.is_(None), Task.due_at, Task.priority.desc()).limit(5)
    ).scalars().all()

    # events (next 7 days)
    upcoming_events = db.execute(
        select(Event).where(
            Event.user_id == user.id, Event.deleted_at.is_(None),
            Event.starts_at >= now - timedelta(hours=1),
            Event.starts_at <= now + timedelta(days=7),
        ).order_by(Event.starts_at).limit(5)
    ).scalars().all()

    # counts
    memory_count = db.execute(
        select(func.count()).select_from(Memory).where(
            Memory.user_id == user.id, Memory.deleted_at.is_(None))
    ).scalar_one()
    unread = db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.read.is_(False))
    ).scalar_one()
    automations_active = db.execute(
        select(func.count()).select_from(Automation).where(
            Automation.user_id == user.id, Automation.enabled.is_(True))
    ).scalar_one()
    pending_confirmations = db.execute(
        select(func.count()).select_from(Confirmation).where(
            Confirmation.user_id == user.id, Confirmation.status == "pending",
            Confirmation.expires_at > now)
    ).scalar_one()

    # recent activity (real audit rows)
    recent = db.execute(
        select(AuditLog).where(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id).limit(6)
    ).scalars().all()

    app_settings = get_settings()

    greeting_hour = local_now.hour
    if greeting_hour < 5:
        greeting = "Good night"
    elif greeting_hour < 12:
        greeting = "Good morning"
    elif greeting_hour < 17:
        greeting = "Good afternoon"
    elif greeting_hour < 22:
        greeting = "Good evening"
    else:
        greeting = "Good night"

    return {
        "greeting": greeting,
        "user_name": user.display_name,
        "local_time": local_now.isoformat(),
        "timezone": str(tz),
        "assistant_name": settings.assistant_name,
        "ai": {
            "configured": bool(app_settings.ai_base_url and app_settings.ai_model),
            "model": app_settings.ai_model,
        },
        "emergency_stop": settings.emergency_stop,
        "memory_enabled": settings.memory_enabled,
        "tasks": {
            "open": open_tasks,
            "due_today": due_today,
            "overdue": overdue,
            "next": [
                {"id": t.id, "title": t.title, "priority": t.priority, "status": t.status,
                 "due_at": t.due_at.isoformat() if t.due_at else None}
                for t in next_tasks
            ],
        },
        "events": [
            {"id": e.id, "title": e.title, "starts_at": e.starts_at.isoformat(),
             "location": e.location}
            for e in upcoming_events
        ],
        "memory_count": memory_count,
        "unread_notifications": unread,
        "automations_active": automations_active,
        "pending_confirmations": pending_confirmations,
        "recent_activity": [
            {"id": a.id, "category": a.category, "action": a.action,
             "created_at": a.created_at.isoformat()}
            for a in recent
        ],
    }
