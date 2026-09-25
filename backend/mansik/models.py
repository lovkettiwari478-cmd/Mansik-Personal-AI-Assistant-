"""SQLAlchemy models.

Every user-owned row carries ``user_id`` with a foreign key to ``users`` and
a non-null constraint — data isolation is enforced at the schema level and
re-checked in every query (defence in depth against IDOR).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    TypeDecorator, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class AwareDateTime(TypeDecorator):
    """DateTime that ALWAYS returns timezone-aware UTC values.

    SQLite loses the tzinfo on round-trip; this normalises on load so that
    comparisons against ``utcnow()`` never mix naive/aware datetimes.
    """
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Users & sessions
# --------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    settings_rel: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")

    def public(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "created_at": self.created_at,
        }


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default="dark", nullable=False)
    # Emergency stop halts ALL tool execution and automations for the user.
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    emergency_stop_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="settings_rel")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    # Only the SHA-256 hash of the cookie token is stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    __table_args__ = (Index("ix_auth_sessions_user_active", "user_id", "revoked_at"),)


# --------------------------------------------------------------------------
# Conversations & messages (short-term memory)
# --------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    # execution metadata: tool calls, confirmations, execution summaries
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


# --------------------------------------------------------------------------
# Long-term memory
# --------------------------------------------------------------------------

class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="fact", nullable=False)  # fact|preference|person|project|goal|event
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=50, nullable=False)  # 0-100
    source: Mapped[str] = mapped_column(String(16), default="explicit")  # explicit | auto
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    __table_args__ = (
        Index("ix_memories_user_kind", "user_id", "kind"),
        Index("ix_memories_user_deleted", "user_id", "deleted_at"),
    )


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="todo", index=True)  # todo|in_progress|done|cancelled
    priority: Mapped[str] = mapped_column(String(16), default="medium")  # low|medium|high|urgent
    due_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    recurrence: Mapped[str] = mapped_column(String(16), default="none")  # none|daily|weekly|monthly
    remind_minutes_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    __table_args__ = (
        Index("ix_tasks_user_status_due", "user_id", "status", "due_at"),
        UniqueConstraint("user_id", "title", "due_at", name="uq_tasks_user_title_due"),
    )


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------

class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    starts_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence: Mapped[str] = mapped_column(String(16), default="none")  # none|daily|weekly|monthly
    reminder_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    __table_args__ = (Index("ix_events_user_start", "user_id", "starts_at"),)


# --------------------------------------------------------------------------
# Automations
# --------------------------------------------------------------------------

class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)  # interval | daily_at
    trigger_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    # e.g. {"every_seconds": 3600} or {"at_hhmm": "09:00", "timezone": "UTC"}
    action_tool: Mapped[str] = mapped_column(String(64), nullable=False)
    action_params: Mapped[dict] = mapped_column(JSON, default=dict)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)
    last_run_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    automation_id: Mapped[str] = mapped_column(ForeignKey("automations.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # success|failed|skipped
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------
# Permission firewall
# --------------------------------------------------------------------------

class PermissionGrant(Base):
    __tablename__ = "permission_grants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. tools:web, email:send
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # standing grants expire; None = until revoked
    expires_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "scope", name="uq_grants_user_scope"),)


class Confirmation(Base):
    __tablename__ = "confirmations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|approved|denied|expired|executed
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    risk: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)


# --------------------------------------------------------------------------
# Audit log (observability + security)
# --------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(24), index=True, nullable=False)  # auth|security|tool|memory|task|calendar|automation|file|system
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    resource: Mapped[str] = mapped_column(String(200), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    request_id: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, index=True)

    __table_args__ = (Index("ix_audit_user_created", "user_id", "created_at"),)


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

class StoredFile(Base):
    __tablename__ = "stored_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(64), nullable=False)  # random, no user input
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # extracted plain text (first N chars) for search/retrieval; empty for binaries
    text_preview: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)


# --------------------------------------------------------------------------
# Knowledge graph
# --------------------------------------------------------------------------

class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(24), default="concept")  # person|project|goal|task|document|event|device|integration|concept
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "type", "name", name="uq_entities_user_type_name"),)


class EntityRelation(Base):
    __tablename__ = "entity_relations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    from_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    to_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), default="related_to")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="info")  # info|warning|action|reminder
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utcnow)


# --------------------------------------------------------------------------
# FTS5 full-text index over memories (SQLite only; PG uses ILIKE fallback)
# --------------------------------------------------------------------------

MEMORY_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='rowid',
    tokenize='porter unicode61'
)
"""

MEMORY_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS memories_fts_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_fts_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_fts_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END
    """,
]
