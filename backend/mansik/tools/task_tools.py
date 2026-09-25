"""Task tools — real CRUD against the user's task list."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select

from ..config import RISK_LOW_WRITE, RISK_READ
from ..errors import NotFoundError
from ..models import Task, utcnow
from ..utils.dates import parse_natural_datetime
from .base import Tool, ToolContext, ToolParams
from pydantic import Field


class TaskCreateParams(ToolParams):
    title: str = Field(..., min_length=1, max_length=300)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due: str | None = Field(None, description="Due date/time, e.g. 'tomorrow 5pm', '2026-01-02 15:00', 'in 2 hours'")
    notes: str = Field("", max_length=5000)
    recurrence: Literal["none", "daily", "weekly", "monthly"] = "none"


class TaskListParams(ToolParams):
    status: Literal["all", "todo", "in_progress", "done", "cancelled"] = "all"
    limit: int = Field(20, ge=1, le=100)


class TaskCompleteParams(ToolParams):
    query: str = Field(..., min_length=1, max_length=300, description="Title (or part of it) of the task to complete")


def _task_json(t: Task) -> dict:
    return {
        "id": t.id, "title": t.title, "notes": t.notes, "status": t.status,
        "priority": t.priority, "due_at": t.due_at.isoformat() if t.due_at else None,
        "recurrence": t.recurrence,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


class TaskCreateTool(Tool):
    id = "tasks.create"
    name = "Create task"
    description = "Create a task with optional priority, due date/time and recurrence."
    category = "productivity"
    risk = RISK_LOW_WRITE
    scope = "tasks:write"
    timeout_seconds = 10.0
    params_model = TaskCreateParams

    async def run(self, ctx: ToolContext, params: TaskCreateParams) -> dict:
        due_at = None
        if params.due:
            due_at = parse_natural_datetime(params.due, tz=ctx.user_settings.timezone or "UTC")
            if due_at is None:
                raise NotFoundError("Could not understand the due date. Try 'tomorrow 5pm' or '2026-01-02 15:00'.")
        task = Task(
            user_id=ctx.user.id,
            title=params.title.strip(),
            notes=params.notes,
            priority=params.priority,
            due_at=due_at,
            recurrence=params.recurrence,
        )
        ctx.db.add(task)
        ctx.db.flush()
        # verification: re-read the row from the database before claiming success
        ctx.db.refresh(task)
        return {"task": _task_json(task), "verified": True}


class TaskListTool(Tool):
    id = "tasks.list"
    name = "List tasks"
    description = "List your tasks, optionally filtered by status."
    category = "productivity"
    risk = RISK_READ
    params_model = TaskListParams

    async def run(self, ctx: ToolContext, params: TaskListParams) -> dict:
        stmt = select(Task).where(Task.user_id == ctx.user.id, Task.deleted_at.is_(None))
        if params.status != "all":
            stmt = stmt.where(Task.status == params.status)
        stmt = stmt.order_by(Task.due_at.is_(None), Task.due_at, Task.created_at.desc()).limit(params.limit)
        tasks = list(ctx.db.execute(stmt).scalars())
        return {"tasks": [_task_json(t) for t in tasks], "count": len(tasks)}


class TaskCompleteTool(Tool):
    id = "tasks.complete"
    name = "Complete task"
    description = "Mark a task as done, matching by title."
    category = "productivity"
    risk = RISK_LOW_WRITE
    scope = "tasks:write"
    timeout_seconds = 10.0
    params_model = TaskCompleteParams

    async def run(self, ctx: ToolContext, params: TaskCompleteParams) -> dict:
        q = params.query.strip().lower()
        stmt = select(Task).where(
            Task.user_id == ctx.user.id, Task.deleted_at.is_(None),
            Task.status.in_(["todo", "in_progress"]),
        )
        candidates = [t for t in ctx.db.execute(stmt).scalars() if q in t.title.lower()]
        if not candidates:
            raise NotFoundError("No open task matching that title.")
        if len(candidates) > 1:
            return {"ambiguous": True, "candidates": [_task_json(t) for t in candidates[:5]],
                    "message": "Multiple tasks match — be more specific."}
        task = candidates[0]
        task.status = "done"
        task.completed_at = utcnow()
        ctx.db.flush()
        return {"task": _task_json(task)}
