"""Background worker: automation execution, reminders, cleanup.

Runs as a daemon thread started once at app startup (single-process mode).
In multi-worker production deployments, run ONE instance (e.g. a dedicated
worker process calling ``start_scheduler()``) — the run lock in the
database prevents duplicate executions within a process, and automations
are idempotent-safe by design.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import timedelta

from sqlalchemy import select

from ..database import session_scope
from ..models import (
    Automation, AutomationRun, Confirmation, Event, Notification, Task,
    User, UserSettings, new_id, utcnow,
)
from ..observability import get_logger, log
from ..permissions.firewall import _active_grant
from ..tools import ToolContext, execute_tool, registry as tool_registry

logger = get_logger("mansik.scheduler")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_stop_event = threading.Event()

# In-memory dedupe of reminders (per process lifetime)
_sent_task_reminders: set[str] = set()
_sent_event_reminders: set[str] = set()


def _drain_pending_confirmations() -> None:
    """Expire stale pending confirmations."""
    with session_scope() as db:
        now = utcnow()
        rows = db.execute(
            select(Confirmation).where(Confirmation.status == "pending",
                                       Confirmation.expires_at <= now)
        ).scalars().all()
        for c in rows:
            c.status = "expired"
        if rows:
            log(logger, "info", "expired confirmations", count=len(rows))


def _run_automations() -> None:
    with session_scope() as db:
        now = utcnow()
        due = db.execute(
            select(Automation).where(Automation.enabled.is_(True), Automation.next_run_at <= now)
        ).scalars().all()
        for a in due:
            _execute_automation(db, a, now)


def _execute_automation(db, a: Automation, now) -> None:
    run = AutomationRun(
        id=new_id(), automation_id=a.id, user_id=a.user_id, status="success",
        attempt=1, started_at=now,
    )
    db.add(run)
    a.last_run_at = now
    settings_row = db.get(UserSettings, a.user_id)
    user = db.get(User, a.user_id)

    try:
        if settings_row is None or user is None:
            raise RuntimeError("owner missing")
        if settings_row.emergency_stop:
            run.status = "skipped"
            run.error = "emergency stop active"
            run.result = {"skipped": True}
        else:
            tool = tool_registry.get(a.action_tool)
            grant = _active_grant(db, a.user_id, tool.scope) if tool.scope else None
            if tool.scope and (grant is None or not grant.allowed):
                # User revoked the permission — skip and note it.
                run.status = "skipped"
                run.error = f"standing grant for '{tool.scope}' missing/revoked"
                run.result = {"skipped": True}
            else:
                ctx = ToolContext(db=db, user=user, user_settings=settings_row,
                                  request_id="", execution_id="")
                result = asyncio.run(execute_tool(
                    ctx, a.action_tool, a.action_params,
                    request_id="", automation_id=a.id,
                ))
                run.status = "success" if result.success else "failed"
                run.error = result.error[:2000]
                run.result = result.output if result.success else {}
    except Exception as exc:  # noqa: BLE001 — worker must never die
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        log(logger, "error", "automation run failed", automation=a.id, error=run.error)

    run.finished_at = utcnow()
    # schedule next run
    from ..api.automations import _compute_next_run
    try:
        a.next_run_at = _compute_next_run(a.trigger_type, a.trigger_config, last_run=a.last_run_at)
    except Exception:
        a.enabled = False
        a.next_run_at = None
    log(logger, "info", "automation run", automation=a.id, name=a.name, status=run.status)


def _send_reminders() -> None:
    now = utcnow()
    with session_scope() as db:
        # Task reminders
        tasks = db.execute(
            select(Task).where(
                Task.deleted_at.is_(None), Task.status.in_(["todo", "in_progress"]),
                Task.due_at.is_not(None), Task.remind_minutes_before.is_not(None),
                Task.due_at <= now + timedelta(minutes=60 * 24),
            )
        ).scalars().all()
        for t in tasks:
            if t.id in _sent_task_reminders or t.remind_minutes_before is None or t.due_at is None:
                continue
            remind_at = t.due_at - timedelta(minutes=t.remind_minutes_before)
            if now >= remind_at:
                db.add(Notification(
                    id=new_id(), user_id=t.user_id, kind="reminder",
                    title=f"Task due: {t.title[:150]}",
                    body=f"Due {t.due_at.isoformat()}" + (f" (priority {t.priority})" if t.priority else ""),
                    created_at=now,
                ))
                _sent_task_reminders.add(t.id)

        # Event reminders
        events = db.execute(
            select(Event).where(
                Event.deleted_at.is_(None), Event.reminder_minutes.is_not(None),
                Event.starts_at <= now + timedelta(hours=48),
            )
        ).scalars().all()
        for e in events:
            if e.id in _sent_event_reminders or e.reminder_minutes is None:
                continue
            remind_at = e.starts_at - timedelta(minutes=e.reminder_minutes)
            if now >= remind_at:
                db.add(Notification(
                    id=new_id(), user_id=e.user_id, kind="reminder",
                    title=f"Upcoming: {e.title[:150]}",
                    body=f"Starts {e.starts_at.isoformat()}" + (f" @ {e.location}" if e.location else ""),
                    created_at=now,
                ))
                _sent_event_reminders.add(e.id)


def _tick() -> None:
    try:
        _drain_pending_confirmations()
        _send_reminders()
        _run_automations()
    except Exception as exc:  # noqa: BLE001
        log(logger, "error", "scheduler tick failed",
            error=f"{type(exc).__name__}: {exc}")
        logger.exception("scheduler_tick_exception")


def _scheduler_loop(interval: int) -> None:
    while not _stop_event.is_set():
        _tick()
        _stop_event.wait(interval)


def start_scheduler(interval_seconds: int = 30) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(
        target=_scheduler_loop, args=(interval_seconds,),
        name="mansik-scheduler", daemon=True,
    )
    _thread.start()
    log(logger, "info", "scheduler started", interval_seconds=interval_seconds)


def stop_scheduler() -> None:
    _stop_event.set()
