"""User-facing labels & agent attribution for tools.

The UI shows friendly progress ("Creating task…") instead of internal
tool ids, and attributes execution to the specialist agent role that
handled it. Purely presentation metadata — no behavioral effect.
"""

from __future__ import annotations

from .base import Tool

# tool_id -> friendly gerund label shown while running
LABELS: dict[str, str] = {
    "tasks.create": "Creating task…",
    "tasks.list": "Checking your tasks…",
    "tasks.complete": "Completing task…",
    "memory.save": "Saving to memory…",
    "memory.search": "Searching your memory…",
    "calendar.create_event": "Scheduling event…",
    "calendar.list_upcoming": "Checking your calendar…",
    "math.calculate": "Calculating…",
    "time.now": "Checking the time…",
    "web.search": "Searching the web…",
    "web.fetch": "Fetching page…",
    "files.list": "Checking your files…",
    "files.read_text": "Reading file…",
    "files.delete": "Deleting file…",
    "notify.user": "Sending notification…",
    "email.send": "Sending email…",
}

# tool category -> specialist agent role
AGENTS: dict[str, str] = {
    "productivity": "Task Agent",
    "memory": "Memory Agent",
    "calendar": "Calendar Agent",
    "web": "Research Agent",
    "files": "Files Agent",
    "communication": "Comms Agent",
    "utility": "Core",
}


def label_for(tool: Tool) -> str:
    return LABELS.get(tool.id, f"Running {tool.name}…")


def agent_for(tool: Tool) -> str:
    return AGENTS.get(tool.category, "Core")
