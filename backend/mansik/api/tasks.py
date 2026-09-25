"""Task endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..errors import NotFoundError, ValidationAppError
from ..models import AuthSession, Task, User, utcnow
from ..observability import audit
from ..security.auth import get_db, require_auth
from .schemas import TaskIn, TaskPatch

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_json(t: Task) -> dict:
    return {
        "id": t.id, "title": t.title, "notes": t.notes, "status": t.status,
        "priority": t.priority, "due_at": t.due_at.isoformat() if t.due_at else None,
        "recurrence": t.recurrence,
        "remind_minutes_before": t.remind_minutes_before,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
    }


def _parse_dt(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationAppError("Invalid datetime format (use ISO 8601, e.g. 2026-01-02T15:00:00+00:00).")
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _own_task(db: DbSession, user: User, task_id: str) -> Task:
    t = db.get(Task, task_id)
    if t is None or t.user_id != user.id or t.deleted_at is not None:
        raise NotFoundError("Task not found.")
    return t


@router.get("")
def list_tasks(
    status: str | None = None,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    stmt = select(Task).where(Task.user_id == user.id, Task.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.due_at.is_(None), Task.due_at, Task.created_at.desc()).limit(500)
    rows = db.execute(stmt).scalars().all()
    return {"tasks": [_task_json(t) for t in rows], "count": len(rows)}


@router.post("", status_code=201)
def create_task(
    body: TaskIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    t = Task(
        user_id=user.id, title=body.title.strip(), notes=body.notes,
        priority=body.priority, due_at=_parse_dt(body.due_at), recurrence=body.recurrence,
        remind_minutes_before=body.remind_minutes_before,
    )
    db.add(t)
    audit(db, event_type="task_created", category="task", action=f"Task created: {t.title[:100]}",
          user_id=user.id, resource=t.id, request_id=request.state.request_id)
    db.commit()
    return {"task": _task_json(t)}


@router.patch("/{task_id}")
def update_task(
    task_id: str, body: TaskPatch, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    t = _own_task(db, user, task_id)
    if body.title is not None:
        t.title = body.title.strip()
    if body.notes is not None:
        t.notes = body.notes
    if body.status is not None:
        t.status = body.status
        t.completed_at = utcnow() if body.status == "done" else None
    if body.priority is not None:
        t.priority = body.priority
    if body.due_at is not None:
        t.due_at = _parse_dt(body.due_at) if body.due_at else None
    if body.recurrence is not None:
        t.recurrence = body.recurrence
    if body.remind_minutes_before is not None:
        t.remind_minutes_before = body.remind_minutes_before
    audit(db, event_type="task_updated", category="task", action=f"Task updated: {t.title[:100]}",
          user_id=user.id, resource=t.id, request_id=request.state.request_id)
    db.commit()
    return {"task": _task_json(t)}


@router.delete("/{task_id}")
def delete_task(
    task_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    t = _own_task(db, user, task_id)
    t.deleted_at = utcnow()
    audit(db, event_type="task_deleted", category="task", action=f"Task deleted: {t.title[:100]}",
          user_id=user.id, resource=t.id, request_id=request.state.request_id)
    db.commit()
    return {"ok": True}
