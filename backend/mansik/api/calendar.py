"""Calendar endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..errors import NotFoundError, ValidationAppError
from ..models import AuthSession, Event, User, utcnow
from ..observability import audit
from ..security.auth import get_db, require_auth
from .schemas import EventIn, EventPatch

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _event_json(e: Event) -> dict:
    return {
        "id": e.id, "title": e.title, "description": e.description, "location": e.location,
        "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat(),
        "all_day": e.all_day, "recurrence": e.recurrence, "reminder_minutes": e.reminder_minutes,
        "created_at": e.created_at.isoformat(),
    }


def _parse_dt(value: str | None, *, required: bool = False) -> datetime | None:
    if value is None or value == "":
        if required:
            raise ValidationAppError("Datetime is required.")
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationAppError("Invalid datetime format (use ISO 8601).")
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _own_event(db: DbSession, user: User, event_id: str) -> Event:
    e = db.get(Event, event_id)
    if e is None or e.user_id != user.id or e.deleted_at is not None:
        raise NotFoundError("Event not found.")
    return e


@router.get("")
def list_events(
    days: int = 30,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    days = max(1, min(days, 365))
    now = utcnow()
    stmt = (
        select(Event)
        .where(
            Event.user_id == user.id, Event.deleted_at.is_(None),
            Event.starts_at >= now - timedelta(days=1),
            Event.starts_at <= now + timedelta(days=days),
        )
        .order_by(Event.starts_at)
        .limit(500)
    )
    rows = db.execute(stmt).scalars().all()
    return {"events": [_event_json(e) for e in rows], "count": len(rows)}


@router.post("", status_code=201)
def create_event(
    body: EventIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    starts = _parse_dt(body.starts_at, required=True)
    ends = _parse_dt(body.ends_at, required=True)
    if ends <= starts:
        raise ValidationAppError("End time must be after start time.")
    e = Event(
        user_id=user.id, title=body.title.strip(), description=body.description,
        location=body.location, starts_at=starts, ends_at=ends,
        all_day=body.all_day, recurrence=body.recurrence, reminder_minutes=body.reminder_minutes,
    )
    db.add(e)
    audit(db, event_type="event_created", category="calendar",
          action=f"Event created: {e.title[:100]}", user_id=user.id, resource=e.id,
          request_id=request.state.request_id)
    db.commit()
    return {"event": _event_json(e)}


@router.patch("/{event_id}")
def update_event(
    event_id: str, body: EventPatch, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    e = _own_event(db, user, event_id)
    if body.title is not None:
        e.title = body.title.strip()
    if body.description is not None:
        e.description = body.description
    if body.location is not None:
        e.location = body.location
    if body.starts_at is not None:
        e.starts_at = _parse_dt(body.starts_at, required=True)
    if body.ends_at is not None:
        e.ends_at = _parse_dt(body.ends_at, required=True)
    if e.ends_at <= e.starts_at:
        raise ValidationAppError("End time must be after start time.")
    if body.all_day is not None:
        e.all_day = body.all_day
    if body.recurrence is not None:
        e.recurrence = body.recurrence
    if body.reminder_minutes is not None:
        e.reminder_minutes = body.reminder_minutes
    audit(db, event_type="event_updated", category="calendar",
          action=f"Event updated: {e.title[:100]}", user_id=user.id, resource=e.id,
          request_id=request.state.request_id)
    db.commit()
    return {"event": _event_json(e)}


@router.delete("/{event_id}")
def delete_event(
    event_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    e = _own_event(db, user, event_id)
    e.deleted_at = utcnow()
    audit(db, event_type="event_deleted", category="calendar",
          action=f"Event deleted: {e.title[:100]}", user_id=user.id, resource=e.id,
          request_id=request.state.request_id)
    db.commit()
    return {"ok": True}
