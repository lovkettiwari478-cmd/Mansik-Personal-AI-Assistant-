"""Calendar tools."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from sqlalchemy import select

from ..config import RISK_LOW_WRITE, RISK_READ
from ..errors import NotFoundError
from ..models import Event
from ..utils.dates import parse_natural_datetime
from .base import Tool, ToolContext, ToolParams
from pydantic import Field


class EventCreateParams(ToolParams):
    title: str = Field(..., min_length=1, max_length=300)
    starts: str = Field(..., description="Start date/time, e.g. 'tomorrow 3pm', '2026-01-02 15:00'")
    duration_minutes: int = Field(60, ge=5, le=24 * 60)
    description: str = Field("", max_length=2000)
    location: str = Field("", max_length=300)
    reminder_minutes: int | None = Field(None, ge=0, le=10080)


class UpcomingParams(ToolParams):
    days: int = Field(7, ge=1, le=90)
    limit: int = Field(10, ge=1, le=50)


def _event_json(e: Event) -> dict:
    return {
        "id": e.id, "title": e.title, "description": e.description, "location": e.location,
        "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat(),
        "all_day": e.all_day, "recurrence": e.recurrence, "reminder_minutes": e.reminder_minutes,
    }


class EventCreateTool(Tool):
    id = "calendar.create_event"
    name = "Create event"
    description = "Create a calendar event with start time, duration and optional reminder."
    category = "calendar"
    risk = RISK_LOW_WRITE
    scope = "calendar:write"
    timeout_seconds = 10.0
    params_model = EventCreateParams

    async def run(self, ctx: ToolContext, params: EventCreateParams) -> dict:
        start = parse_natural_datetime(params.starts, tz=ctx.user_settings.timezone or "UTC")
        if start is None:
            raise NotFoundError("Could not understand the start time. Try 'tomorrow 3pm' or '2026-01-02 15:00'.")
        # Detect conflicting events for the same user (basic overlap check)
        from ..models import utcnow
        window_end = start + timedelta(minutes=params.duration_minutes)
        stmt = select(Event).where(
            Event.user_id == ctx.user.id, Event.deleted_at.is_(None),
            Event.starts_at < window_end, Event.ends_at > start,
        )
        conflicts = list(ctx.db.execute(stmt).scalars())
        event = Event(
            user_id=ctx.user.id,
            title=params.title.strip(),
            description=params.description,
            location=params.location,
            starts_at=start,
            ends_at=window_end,
            reminder_minutes=params.reminder_minutes,
        )
        ctx.db.add(event)
        ctx.db.flush()
        # verification: re-read the row from the database before claiming success
        ctx.db.refresh(event)
        result = {"event": _event_json(event), "verified": True}
        if conflicts:
            result["conflicts"] = [_event_json(c) for c in conflicts[:3]]
            result["note"] = "This event overlaps with existing events (see conflicts)."
        return result


class UpcomingEventsTool(Tool):
    id = "calendar.list_upcoming"
    name = "Upcoming events"
    description = "List upcoming calendar events for the next N days."
    category = "calendar"
    risk = RISK_READ
    params_model = UpcomingParams

    async def run(self, ctx: ToolContext, params: UpcomingParams) -> dict:
        from ..models import utcnow
        now = utcnow()
        stmt = (
            select(Event)
            .where(
                Event.user_id == ctx.user.id, Event.deleted_at.is_(None),
                Event.starts_at >= now - timedelta(hours=2),
                Event.starts_at <= now + timedelta(days=params.days),
            )
            .order_by(Event.starts_at)
            .limit(params.limit)
        )
        events = list(ctx.db.execute(stmt).scalars())
        return {"events": [_event_json(e) for e in events], "count": len(events)}
