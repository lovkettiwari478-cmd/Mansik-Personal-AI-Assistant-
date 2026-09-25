"""Memory tools — explicit long-term memory with user control."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select

from ..config import RISK_LOW_WRITE, RISK_READ
from ..errors import ValidationAppError
from ..memory.service import search_memories
from ..models import Memory, new_id, utcnow
from .base import Tool, ToolContext, ToolParams
from pydantic import Field, field_validator

MEMORY_KINDS = ("fact", "preference", "person", "project", "goal", "event")


def _memory_json(m: Memory) -> dict:
    return {
        "id": m.id, "kind": m.kind, "content": m.content,
        "importance": m.importance, "source": m.source,
        "created_at": m.created_at.isoformat(), "updated_at": m.updated_at.isoformat(),
    }


class MemorySaveParams(ToolParams):
    content: str = Field(..., min_length=3, max_length=2000)
    kind: Literal["fact", "preference", "person", "project", "goal", "event"] = "fact"
    importance: int = Field(50, ge=0, le=100)

    @field_validator("content")
    @classmethod
    def _no_secrets(cls, v: str) -> str:
        lowered = v.lower()
        if any(s in lowered for s in ("password", "api key", "secret key", "private key")):
            raise ValidationAppError(
                "This looks like it may contain credentials. MANISK refuses to store secrets in memory."
            )
        return v.strip()


class MemorySearchParams(ToolParams):
    query: str = Field(..., min_length=1, max_length=300)
    limit: int = Field(5, ge=1, le=20)


class MemorySaveTool(Tool):
    id = "memory.save"
    name = "Save memory"
    description = "Store an explicit long-term memory (fact, preference, person, project, goal or event)."
    category = "memory"
    risk = RISK_LOW_WRITE
    scope = "memory:write"
    timeout_seconds = 10.0
    params_model = MemorySaveParams

    async def run(self, ctx: ToolContext, params: MemorySaveParams) -> dict:
        if not ctx.user_settings.memory_enabled:
            raise ValidationAppError("Memory is disabled in your settings.")
        memory = Memory(
            id=new_id(),
            user_id=ctx.user.id,
            kind=params.kind,
            content=params.content,
            importance=params.importance,
            source="explicit",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        ctx.db.add(memory)
        ctx.db.flush()
        # verification: re-read the row from the database before claiming success
        ctx.db.refresh(memory)
        return {"memory": _memory_json(memory), "verified": True}


class MemorySearchTool(Tool):
    id = "memory.search"
    name = "Search memory"
    description = "Search your long-term memories with full-text search."
    category = "memory"
    risk = RISK_READ
    params_model = MemorySearchParams

    async def run(self, ctx: ToolContext, params: MemorySearchParams) -> dict:
        results = search_memories(ctx.db, ctx.user.id, params.query, limit=params.limit)
        return {"memories": [_memory_json(m) for m in results], "count": len(results)}
