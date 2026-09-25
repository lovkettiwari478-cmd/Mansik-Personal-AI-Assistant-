"""Context engine — assembles everything the model (or local router) sees.

Separates: conversation history (short-term), retrieved long-term memory,
user preferences, task context, and current time. Memory retrieval is
disabled when the user turned memory off, and retrieved memories are always
attributed in message metadata (privacy requirement).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..memory.service import search_memories
from ..models import Memory, Message, Task, User, UserSettings


def recent_messages(db: DbSession, conversation_id: str, limit: int = 20) -> list[Message]:
    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    ).scalars().all()
    return list(reversed(list(rows)))


def relevant_memories(
    db: DbSession, user: User, user_settings: UserSettings, query: str, limit: int = 5,
) -> list[Memory]:
    if not user_settings.memory_enabled or not query.strip():
        return []
    # take keywords from the query
    return search_memories(db, user.id, query, limit=limit)


def open_tasks_context(db: DbSession, user_id: str, limit: int = 5) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.user_id == user_id, Task.deleted_at.is_(None),
               Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_at.is_(None), Task.due_at, Task.priority.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def current_time_context(user_settings: UserSettings) -> dict:
    try:
        tz = ZoneInfo(user_settings.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    return {"iso": now.isoformat(), "timezone": str(tz), "weekday": now.strftime("%A")}


def build_context_block(
    db: DbSession, user: User, user_settings: UserSettings, query: str,
) -> tuple[str, list[Memory]]:
    """Returns (context_text_for_model, memories_used) — memories are
    surfaced to the UI for attribution."""
    parts: list[str] = []
    memories = relevant_memories(db, user, user_settings, query)
    if memories:
        mem_lines = "\n".join(f"- [{m.kind}] {m.content}" for m in memories)
        parts.append(f"RELEVANT MEMORIES (user-controlled; may be empty):\n{mem_lines}")
    tasks = open_tasks_context(db, user.id)
    if tasks:
        task_lines = "\n".join(
            f"- {t.title} (status: {t.status}, priority: {t.priority}"
            + (f", due: {t.due_at.isoformat()}" if t.due_at else "") + ")"
            for t in tasks
        )
        parts.append(f"USER'S OPEN TASKS:\n{task_lines}")
    tctx = current_time_context(user_settings)
    parts.append(
        f"CURRENT TIME: {tctx['iso']} ({tctx['timezone']}, {tctx['weekday']})"
    )
    parts.append(f"USER: {user.display_name} (id: {user.id[:8]}…). Memory enabled: {user_settings.memory_enabled}.")
    return "\n\n".join(parts), memories
