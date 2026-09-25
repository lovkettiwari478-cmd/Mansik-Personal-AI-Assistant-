"""Local Mode — deterministic command routing when no AI provider is
configured.

This is NOT an AI and never pretends to be: it recognises a fixed set of
command patterns and routes them through the exact same tool/permission
pipeline the AI planner uses. Anything it cannot parse gets an honest
explanation plus usage examples. No fabricated intelligence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class LocalPlan:
    reply: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    intent: str = "unknown"


_DUE_RE = re.compile(
    r"\b(?:due|by|at|on|before)\s+(.*?)(?=$|;|,| and | with | priority)", re.IGNORECASE
)
_PRIORITY_RE = re.compile(r"\b(urgent|high|medium|low)\s+priority\b|\bpriority\s+(urgent|high|medium|low)\b", re.IGNORECASE)
_TIME_HINT_RE = re.compile(
    r"\b(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"in \d+ (?:minutes?|mins?|hours?|hrs?|days?|weeks?)|next \w+|\d{1,2}:\d{2}|\d{1,2}\s?(?:am|pm))\b",
    re.IGNORECASE,
)


def _extract_due(text: str) -> str | None:
    """Extract the due phrase. When a day/time word ("tomorrow", "next
    monday", "in 2 hours"…) appears EARLIER than a "due/by/at …" clause,
    prefer it — "buy milk tomorrow at 5pm" should yield the full
    "tomorrow at 5pm", not just "5pm" with "tomorrow" left in the title."""
    candidates: list[tuple[int, str]] = []
    m = _DUE_RE.search(text)
    if m:
        due = m.group(1).strip()
        if due and len(due) < 80:
            candidates.append((m.start(1), due))
    h = _TIME_HINT_RE.search(text)
    if h:
        tail = text[h.start():]
        stop = re.search(r"($|;|,| and | with | priority)", tail, re.IGNORECASE)
        due = tail[: stop.start()].strip().rstrip(".,!?") if stop else tail.strip()
        # drop a trailing priority word captured before the terminator
        due = re.sub(r"\s+(?:urgent|high|medium|low)\s*$", "", due, flags=re.IGNORECASE)
        if due and len(due) < 80:
            candidates.append((h.start(), due))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])[1]


def _extract_priority(text: str) -> str:
    m = _PRIORITY_RE.search(text)
    if m:
        return (m.group(1) or m.group(2)).lower()
    return "medium"


def route_local(message: str) -> LocalPlan:
    msg = message.strip()
    low = msg.lower()

    # --- help -----------------------------------------------------------------
    if low in ("help", "?", "what can you do", "what can you do?"):
        return LocalPlan(reply=_help_text(), intent="help")

    # --- memory: save ----------------------------------------------------------
    m = re.match(r"^(?:please\s+)?remember(?:\s+that)?[:\s]+(.+)$", low, re.IGNORECASE)
    if m and len(m.group(1)) > 2:
        content = msg[m.start(1):m.end(1)].strip()
        return LocalPlan(
            tool_calls=[{"tool": "memory.save", "params": {"content": content[:2000], "kind": "fact"}, "reason": "explicit remember command"}],
            intent="memory.save",
        )

    # --- memory: search ---------------------------------------------------------
    m = re.search(r"what do you (?:remember|know) about (.+?)\??$", low)
    if m:
        return LocalPlan(
            tool_calls=[{"tool": "memory.search", "params": {"query": msg[m.start(1):m.end(1)].strip()[:300]},
                         "reason": "user asked what is remembered"}],
            intent="memory.search",
        )
    m = re.search(r"^(?:search|find)\s+(?:my\s+)?memor(?:y|ies)\s+(?:for|about|containing)\s+(.+)$", low)
    if m:
        return LocalPlan(
            tool_calls=[{"tool": "memory.search", "params": {"query": msg[m.start(1):m.end(1)].strip()[:300]},
                         "reason": "user asked to search memory"}],
            intent="memory.search",
        )

    # --- tasks: create ----------------------------------------------------------
    m = re.match(r"^(?:please\s+)?(?:create|add|new)\s+(?:a\s+)?task[:\s]+(.+)$", low)
    if m:
        return _task_plan(msg[m.start(1):m.end(1)])
    m = re.match(r"^(?:please\s+)?remind me to (.+)$", low)
    if m:
        return _task_plan(msg[m.start(1):m.end(1)], remind=True)

    # --- tasks: list --------------------------------------------------------------
    if re.search(r"\b(?:list|show|what(?:'s| is)? (?:are )?)(?:my |the )?(?:tasks|todos?|to-dos?)\b", low) or low in ("tasks", "my tasks", "todo", "todos"):
        return LocalPlan(tool_calls=[{"tool": "tasks.list", "params": {"status": "all"}}], intent="tasks.list")

    # --- tasks: complete ------------------------------------------------------------
    m = re.match(r"^(?:mark|complete|finish|done)\s+(?:task\s+)?(.+?)(?:\s+as\s+(?:done|complete|completed))?$", low)
    if m and not low.startswith("mark all"):
        return LocalPlan(
            tool_calls=[{"tool": "tasks.complete", "params": {"query": msg[m.start(1):m.end(1)].strip()[:300]},
                         "reason": "user marked task done"}],
            intent="tasks.complete",
        )
    m = re.match(r"^i (?:finished|completed|did)\s+(?:the\s+)?(?:task\s+)?(.+)$", low)
    if m:
        return LocalPlan(
            tool_calls=[{"tool": "tasks.complete", "params": {"query": msg[m.start(1):m.end(1)].strip()[:300]},
                         "reason": "user said they finished it"}],
            intent="tasks.complete",
        )

    # --- calendar: create --------------------------------------------------------------
    m = re.match(r"^(?:please\s+)?(?:schedule|create|add|book)\s+(?:an?\s+)?(?:event|meeting|appointment|call)[:\s]+(.+)$", low)
    if m:
        return _event_plan(msg[m.start(1):m.end(1)])
    # generic "schedule X <time>" — only when a time hint is present
    m = re.match(r"^(?:please\s+)?schedule\s+(.+)$", low)
    if m and _TIME_HINT_RE.search(m.group(1)):
        return _event_plan(msg[m.start(1):m.end(1)])
    m = re.match(r"^(?:please\s+)?(?:meet|call|meeting)\s+(.+?)\s+(at|on|tomorrow|today|next)\s+(.+)$", low)
    if m:
        return _event_plan(msg[m.start(1):m.end(1)])

    # --- calendar: list ------------------------------------------------------------------
    if re.search(r"\b(?:what'?s on |show |list )?(?:my |the )?calendar\b", low) or "upcoming events" in low or "my schedule" in low:
        days = 7
        m = re.search(r"next (\d+) days?", low)
        if m:
            days = min(int(m.group(1)), 90)
        return LocalPlan(tool_calls=[{"tool": "calendar.list_upcoming", "params": {"days": days}}], intent="calendar.list")

    # --- calculator -------------------------------------------------------------------------
    m = re.match(r"^(?:what(?:'s| is)\s+)?((?:[\d\s\.\+\-\*/%\(\)\^÷×,]|sqrt|sin|cos|tan|log|exp|floor|ceil|round|min|max|abs|\b)+)\??$", low)
    if m and re.search(r"\d", low) and re.search(r"[\+\-\*/%\^÷×]", low):
        return LocalPlan(
            tool_calls=[{"tool": "math.calculate", "params": {"expression": msg[m.start(1):m.end(1)]},
                         "reason": "arithmetic"}],
            intent="math.calculate",
        )
    m = re.match(r"^(?:calculate|compute|eval(?:uate)?)\s+(.+)$", low)
    if m:
        return LocalPlan(
            tool_calls=[{"tool": "math.calculate", "params": {"expression": msg[m.start(1):m.end(1)]},
                         "reason": "explicit calculation"}],
            intent="math.calculate",
        )

    # --- time ----------------------------------------------------------------------------------
    if re.search(r"\bwhat time is it\b|\bcurrent time\b|\bwhat'?s the (date|time) today\b|\btoday'?s date\b", low):
        return LocalPlan(tool_calls=[{"tool": "time.now", "params": {}}], intent="time.now")

    # --- web search (external → firewall will require confirmation) -----------------------------
    m = re.match(r"^(?:search the web for|web search|search for|search|google|look up)\s+(.+)$", low)
    if m:
        return LocalPlan(
            tool_calls=[{"tool": "web.search", "params": {"query": msg[m.start(1):m.end(1)].strip()[:300]},
                         "reason": "user asked for a web search"}],
            intent="web.search",
        )

    # --- web fetch (external → firewall confirmation; SSRF-guarded tool) --------------------------
    m = re.match(r"^(?:fetch|open|read)\s+(?:the\s+)?(?:url\s+)?(https?://\S+)$", low)
    if m:
        url = m.group(1).strip()
        return LocalPlan(
            tool_calls=[{"tool": "web.fetch", "params": {"url": url},
                         "reason": "user asked to fetch a URL"}],
            intent="web.fetch",
        )

    # --- files ------------------------------------------------------------------------------------
    if low in ("list files", "my files", "show files", "files"):
        return LocalPlan(tool_calls=[{"tool": "files.list", "params": {}}], intent="files.list")

    # --- fallback: honest local-mode message ---------------------------------------------------------
    return LocalPlan(reply=_local_fallback(msg), intent="fallback")


def _task_plan(raw: str, remind: bool = False) -> LocalPlan:
    raw = raw.strip()
    due = _extract_due(raw)
    title = raw
    if due:
        # strip the due phrase from the title (rough but deterministic);
        # remove the full phrase FIRST so it still matches verbatim
        title = re.sub(re.escape(due), " ", raw, flags=re.IGNORECASE)
        title = re.sub(r"\b(?:due|by|at|on|before)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\bwith\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:high|medium|low|urgent)\s+priority\b|\bpriority\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" ,.-") or raw
    params: dict = {"title": title[:300], "priority": _extract_priority(raw)}
    if due:
        params["due"] = due
    return LocalPlan(
        tool_calls=[{"tool": "tasks.create", "params": params, "reason": "user asked to create a task"}],
        intent="tasks.create",
    )


def _event_plan(rest: str) -> LocalPlan:
    rest = rest.strip()
    due = _extract_due(rest) or ""
    title = rest
    if due:
        title = re.sub(re.escape(due), " ", rest, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:due|by|at|on|before)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" ,.-") or rest
    params: dict = {"title": title[:300], "starts": due or rest}
    return LocalPlan(
        tool_calls=[{"tool": "calendar.create_event", "params": params, "reason": "user asked to schedule"}],
        intent="calendar.create_event",
    )


def _help_text() -> str:
    return (
        "**MANISK — Local Mode help**\n\n"
        "No AI provider is configured on this deployment, so I'm running deterministic "
        "local routing: I can execute real commands through the same tools and permission "
        "system as full AI mode.\n\n"
        "**Try:**\n"
        "- `create task Buy groceries due tomorrow 5pm with high priority`\n"
        "- `remind me to call the bank tomorrow 10am`\n"
        "- `show my tasks` / `complete task Buy groceries`\n"
        "- `schedule Dentist appointment next monday 3pm`\n"
        "- `what's on my calendar`\n"
        "- `remember that my sister's birthday is May 12`\n"
        "- `what do you remember about my sister`\n"
        "- `what is 12 * (8+4)`\n"
        "- `what time is it`\n"
        "- `search the web for neural interface research` (needs confirmation)\n\n"
        "**To enable full AI conversation**, the operator must set "
        "`MANISK_AI_BASE_URL`, `MANISK_AI_MODEL` (and `MANISK_AI_API_KEY` if the provider "
        "requires one). See Settings → AI provider."
    )


def _local_fallback(msg: str) -> str:
    return (
        "I'm running in **Local Mode** — no AI provider is configured on this deployment, "
        "so I can't hold a free-form conversation. I won't pretend otherwise.\n\n"
        "I *can* run real commands for you. Try `help` for examples (tasks, calendar, "
        "memory, math, time, web search).\n\n"
        "To unlock full AI conversation, configure an AI provider "
        "(`MANISK_AI_BASE_URL` + `MANISK_AI_MODEL`, e.g. NVIDIA NIM with Nemotron, OpenAI, "
        "Groq, Together, or a local Ollama)."
    )
