"""Tool registration — every tool available to the orchestrator."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry, ToolResult, execute_tool, registry
from .calculator import CalculatorTool, safe_calculate
from .time_tools import TimeTool
from .task_tools import TaskCompleteTool, TaskCreateTool, TaskListTool
from .memory_tools import MemorySaveTool, MemorySearchTool
from .calendar_tools import EventCreateTool, UpcomingEventsTool
from .web_tools import WebFetchTool, WebSearchTool
from .file_tools import FileDeleteTool, FileListTool, FileReadTool
from .communication_tools import EmailTool, NotifyTool


def register_all() -> ToolRegistry:
    for tool in (
        TimeTool(),
        CalculatorTool(),
        TaskCreateTool(),
        TaskListTool(),
        TaskCompleteTool(),
        MemorySaveTool(),
        MemorySearchTool(),
        EventCreateTool(),
        UpcomingEventsTool(),
        WebSearchTool(),
        WebFetchTool(),
        FileListTool(),
        FileReadTool(),
        FileDeleteTool(),
        NotifyTool(),
        EmailTool(),
    ):
        if tool.id not in registry._tools:
            registry.register(tool)
    return registry


register_all()
