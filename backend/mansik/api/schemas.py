"""API request/response schemas (Pydantic v2, strict)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- auth ------------------------------------------------------------------

class RegisterIn(StrictModel):
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=256)
    display_name: str = Field(..., min_length=1, max_length=120)


class LoginIn(StrictModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)


class ChangePasswordIn(StrictModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=10, max_length=256)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    created_at: str


# --- chat ------------------------------------------------------------------

class ChatIn(StrictModel):
    conversation_id: str | None = None
    message: str = Field(..., min_length=1, max_length=8000)


# --- memory ----------------------------------------------------------------

class MemoryIn(StrictModel):
    content: str = Field(..., min_length=3, max_length=2000)
    kind: Literal["fact", "preference", "person", "project", "goal", "event"] = "fact"
    importance: int = Field(50, ge=0, le=100)


class MemoryPatch(StrictModel):
    content: str | None = Field(None, min_length=3, max_length=2000)
    kind: Literal["fact", "preference", "person", "project", "goal", "event"] | None = None
    importance: int | None = Field(None, ge=0, le=100)


class MemorySearchIn(StrictModel):
    query: str = Field(..., min_length=1, max_length=300)
    limit: int = Field(10, ge=1, le=50)


# --- tasks ------------------------------------------------------------------

class TaskIn(StrictModel):
    title: str = Field(..., min_length=1, max_length=300)
    notes: str = Field("", max_length=5000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_at: str | None = Field(None, max_length=40)
    recurrence: Literal["none", "daily", "weekly", "monthly"] = "none"
    remind_minutes_before: int | None = Field(None, ge=0, le=10080)


class TaskPatch(StrictModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    notes: str | None = Field(None, max_length=5000)
    status: Literal["todo", "in_progress", "done", "cancelled"] | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    due_at: str | None = Field(None, max_length=40)
    recurrence: Literal["none", "daily", "weekly", "monthly"] | None = None
    remind_minutes_before: int | None = Field(None, ge=0, le=10080)


# --- calendar ----------------------------------------------------------------

class EventIn(StrictModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field("", max_length=2000)
    location: str = Field("", max_length=300)
    starts_at: str = Field(..., max_length=40)
    ends_at: str = Field(..., max_length=40)
    all_day: bool = False
    recurrence: Literal["none", "daily", "weekly", "monthly"] = "none"
    reminder_minutes: int | None = Field(None, ge=0, le=10080)


class EventPatch(StrictModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    description: str | None = Field(None, max_length=2000)
    location: str | None = Field(None, max_length=300)
    starts_at: str | None = Field(None, max_length=40)
    ends_at: str | None = Field(None, max_length=40)
    all_day: bool | None = None
    recurrence: Literal["none", "daily", "weekly", "monthly"] | None = None
    reminder_minutes: int | None = Field(None, ge=0, le=10080)


# --- automations ---------------------------------------------------------------

class AutomationIn(StrictModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    trigger_type: Literal["interval", "daily_at"]
    trigger_config: dict = Field(..., description="interval: {every_seconds:int≥300} | daily_at: {at_hhmm:'HH:MM', timezone:'UTC'}")
    action_tool: str = Field(..., max_length=64)
    action_params: dict = Field(default_factory=dict)
    enabled: bool = False
    max_retries: int = Field(1, ge=0, le=3)


class AutomationPatch(StrictModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    trigger_config: dict | None = None
    action_params: dict | None = None
    enabled: bool | None = None
    max_retries: int | None = Field(None, ge=0, le=3)


# --- graph ---------------------------------------------------------------------

class EntityIn(StrictModel):
    type: Literal["person", "project", "goal", "task", "document", "event", "device", "integration", "concept"] = "concept"
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)


class RelationIn(StrictModel):
    from_entity_id: str = Field(..., max_length=64)
    to_entity_id: str = Field(..., max_length=64)
    relation_type: str = Field("related_to", min_length=1, max_length=64)


# --- settings -------------------------------------------------------------------

class SettingsPatch(StrictModel):
    display_name: str | None = Field(None, min_length=1, max_length=120)
    timezone: str | None = Field(None, max_length=64)
    theme: Literal["dark", "light"] | None = None
    memory_enabled: bool | None = None


# --- security ---------------------------------------------------------------------

class GrantIn(StrictModel):
    scope: str = Field(..., max_length=64)
    allowed: bool
    note: str = Field("", max_length=300)


class EmergencyStopIn(StrictModel):
    enabled: bool
