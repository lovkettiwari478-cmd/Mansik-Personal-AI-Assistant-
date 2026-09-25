"""Permission scopes.

A scope names a capability a tool (or automation) needs. Users can grant a
scope persistently (with optional expiry) or approve per-action through the
confirmation flow. Denials always win over grants.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    key: str
    label: str
    description: str
    risk: str  # primary risk if exercised
    grants_persistently: bool  # can the user pre-authorize this scope at all


SCOPES: dict[str, Scope] = {
    s.key: s
    for s in [
        Scope("tasks:write", "Manage tasks", "Create, update and complete your tasks.", "low_risk_write", True),
        Scope("memory:write", "Store memories", "Save long-term memories about you.", "low_risk_write", True),
        Scope("calendar:write", "Manage calendar", "Create and update your calendar events.", "low_risk_write", True),
        Scope("files:write", "Manage files", "Upload and delete files in your private storage.", "high_risk_write", True),
        Scope("notify", "Notifications", "Create in-app notifications and reminders for you.", "low_risk_write", True),
        Scope("tools:web", "Outbound web access", "Search the web and fetch public URLs on your behalf.", "external_communication", True),
        Scope("email:send", "Send email", "Send emails from your configured address. Every send is audited.", "external_communication", True),
        Scope("automation:manage", "Run automations", "Allow saved automations to execute their configured tools.", "high_risk_write", True),
    ]
}


def scope_for(key: str) -> Scope | None:
    return SCOPES.get(key)
