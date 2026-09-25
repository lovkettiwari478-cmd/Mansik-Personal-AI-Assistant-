"""Audit logging — the security-relevant event record.

Every sensitive action (auth events, tool executions, permission changes,
memory mutations, automations) writes an immutable AuditLog row.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog, new_id, utcnow


def audit(
    session: Session,
    *,
    event_type: str,
    category: str,
    action: str,
    user_id: str | None = None,
    resource: str = "",
    ip: str = "",
    user_agent: str = "",
    request_id: str = "",
    detail: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        id=new_id(),
        event_type=event_type,
        category=category,
        action=action,
        user_id=user_id,
        resource=(resource or "")[:200],
        ip=(ip or "")[:64],
        user_agent=(user_agent or "")[:255],
        request_id=request_id,
        detail=detail or {},
        created_at=utcnow(),
    )
    session.add(entry)
    return entry
