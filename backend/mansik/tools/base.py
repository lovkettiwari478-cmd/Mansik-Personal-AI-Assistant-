"""Tool system foundation.

Tools are the ONLY way MANISK acts on the world. Every tool:

- has a unique id, human description, and category
- declares a risk level and permission scope
- validates its input with a strict Pydantic model (unknown fields rejected)
- returns JSON-serializable output (size-limited)
- runs under a hard timeout
- is audited on every execution

There is deliberately NO generic "run code" or "shell" tool.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, ClassVar, Type

from pydantic import BaseModel, ConfigDict

from ..config import RISK_READ, get_settings
from ..errors import AppError, NotFoundError, ValidationAppError
from ..models import User, UserSettings
from ..observability import audit


class ToolParams(BaseModel):
    """Base for tool inputs: strict — extra fields are rejected."""
    model_config = ConfigDict(extra="forbid")


@dataclass
class ToolContext:
    db: Any  # sqlalchemy Session
    user: User
    user_settings: UserSettings
    request_id: str = ""
    execution_id: str = ""


@dataclass
class ToolResult:
    success: bool
    output: dict = field(default_factory=dict)
    error: str = ""

    def to_json(self) -> dict:
        payload = {"success": self.success}
        if self.output:
            payload["output"] = self.output
        if self.error:
            payload["error"] = self.error
        return payload


MAX_TOOL_OUTPUT_BYTES = 200_000


def _check_size(output: dict) -> None:
    try:
        size = len(json.dumps(output, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        raise ValidationAppError("Tool output was not JSON-serializable.")
    if size > MAX_TOOL_OUTPUT_BYTES:
        raise ValidationAppError("Tool output exceeded size limit.")


class Tool:
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    category: ClassVar[str] = "general"
    risk: ClassVar[str] = RISK_READ
    scope: ClassVar[str | None] = None
    timeout_seconds: ClassVar[float] = 15.0
    params_model: ClassVar[Type[ToolParams]] = ToolParams

    #: If False, the tool cannot run in this deployment (e.g. missing
    #: credentials). Must be HONEST — never pretend unconfigured tools work.
    def available(self, ctx: ToolContext) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return "Not configured in this deployment."

    async def run(self, ctx: ToolContext, params: ToolParams) -> dict:
        raise NotImplementedError

    # -- helper for sync work ------------------------------------------------
    @staticmethod
    async def run_sync(fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.id in self._tools:
            raise RuntimeError(f"Duplicate tool id: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> Tool:
        tool = self._tools.get(tool_id)
        if tool is None:
            raise NotFoundError(f"Unknown tool: {tool_id}", code="unknown_tool")
        return tool

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def describe(self, tool: Tool, ctx: ToolContext | None = None) -> dict:
        return {
            "id": tool.id,
            "name": tool.name,
            "description": tool.description,
            "category": tool.category,
            "risk": tool.risk,
            "scope": tool.scope,
            "timeout_seconds": tool.timeout_seconds,
            "params_schema": tool.params_model.model_json_schema(),
            "available": tool.available(ctx) if ctx else True,
            "unavailable_reason": None if (ctx is None or tool.available(ctx)) else tool.unavailable_reason(),
        }


registry = ToolRegistry()


async def execute_tool(
    ctx: ToolContext,
    tool_id: str,
    params: dict,
    *,
    request_id: str = "",
    ip: str = "",
    automation_id: str | None = None,
) -> ToolResult:
    """Validate → execute (with timeout) → validate output → audit."""
    import time as _time

    tool = registry.get(tool_id)
    started = _time.perf_counter()
    ok = False
    error = ""
    output: dict = {}

    if not tool.available(ctx):
        error = tool.unavailable_reason()
        audit(ctx.db, event_type="tool_unavailable", category="tool",
              action=f"{tool_id} unavailable: {error}", user_id=ctx.user.id,
              resource=tool_id, request_id=request_id, ip=ip)
        return ToolResult(success=False, error=error)

    try:
        validated = tool.params_model.model_validate(params or {})
    except Exception as exc:
        error = f"Invalid parameters: {str(exc)[:300]}"
        audit(ctx.db, event_type="tool_invalid_params", category="tool",
              action=error, user_id=ctx.user.id, resource=tool_id,
              request_id=request_id, ip=ip)
        return ToolResult(success=False, error=error)

    try:
        output = await asyncio.wait_for(tool.run(ctx, validated), timeout=tool.timeout_seconds)
        _check_size(output)
        ok = True
    except AppError as exc:
        error = exc.message
    except asyncio.TimeoutError:
        error = f"Tool timed out after {tool.timeout_seconds:.0f}s."
    except Exception as exc:  # tool bugs must not crash the request
        from ..observability import get_logger
        get_logger("mansik.tools").exception("tool_crash")
        error = "Tool failed unexpectedly."
        output = {}

    duration_ms = round((_time.perf_counter() - started) * 1000, 1)
    audit(ctx.db, event_type="tool_executed" if ok else "tool_failed", category="tool",
          action=f"{tool_id} {'ok' if ok else 'failed'}",
          user_id=ctx.user.id, resource=tool_id, request_id=request_id, ip=ip,
          detail={"duration_ms": duration_ms, "automation_id": automation_id,
                  "ok": ok, "error": error[:300] if error else None})
    return ToolResult(success=ok, output=output, error=error)
