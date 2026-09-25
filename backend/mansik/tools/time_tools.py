"""Time tools."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import RISK_READ
from .base import Tool, ToolContext
from pydantic import Field


class NowParams:
    pass


class TimeTool(Tool):
    id = "time.now"
    name = "Current time"
    description = "Get the current date and time in the user's timezone (and UTC)."
    category = "utility"
    risk = RISK_READ

    async def run(self, ctx: ToolContext, params) -> dict:
        try:
            tz = ZoneInfo(ctx.user_settings.timezone or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        return {
            "iso": now.isoformat(),
            "utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "timezone": str(tz),
            "weekday": now.strftime("%A"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
        }
