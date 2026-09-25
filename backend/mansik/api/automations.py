"""Automation endpoints — explicit user authorization, execution logs,
cancellation and emergency-stop awareness."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..errors import ForbiddenError, NotFoundError, ValidationAppError
from ..models import AuthSession, Automation, AutomationRun, User, UserSettings, utcnow
from ..observability import audit
from ..permissions.firewall import PermissionFirewall
from ..security.auth import ensure_user_settings, get_db, require_auth
from ..tools import registry as tool_registry
from .schemas import AutomationIn, AutomationPatch

router = APIRouter(prefix="/api/automations", tags=["automations"])

MIN_INTERVAL_SECONDS = 300  # 5 minutes — protects against runaway loops
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _automation_json(a: Automation) -> dict:
    return {
        "id": a.id, "name": a.name, "description": a.description, "enabled": a.enabled,
        "trigger_type": a.trigger_type, "trigger_config": a.trigger_config,
        "action_tool": a.action_tool, "action_params": a.action_params,
        "max_retries": a.max_retries,
        "last_run_at": a.last_run_at.isoformat() if a.last_run_at else None,
        "next_run_at": a.next_run_at.isoformat() if a.next_run_at else None,
        "created_at": a.created_at.isoformat(),
    }


def _compute_next_run(trigger_type: str, cfg: dict, *, last_run: datetime | None = None) -> datetime:
    now = utcnow()
    if trigger_type == "interval":
        every = int(cfg.get("every_seconds", 0))
        if every < MIN_INTERVAL_SECONDS:
            raise ValidationAppError(f"Interval must be at least {MIN_INTERVAL_SECONDS} seconds.")
        base = last_run or now
        nxt = base + timedelta(seconds=every)
        while nxt <= now:
            nxt += timedelta(seconds=every)
        return nxt
    if trigger_type == "daily_at":
        hhmm = str(cfg.get("at_hhmm", ""))
        if not _HHMM_RE.match(hhmm):
            raise ValidationAppError("at_hhmm must be HH:MM (24h).")
        hour, minute = int(hhmm[:2]), int(hhmm[3:])
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        return nxt
    raise ValidationAppError("trigger_type must be 'interval' or 'daily_at'.")


def _validate_action(tool_id: str, params: dict) -> None:
    try:
        tool = tool_registry.get(tool_id)
    except NotFoundError:
        raise ValidationAppError(f"Unknown tool: {tool_id}")
    # Only allow tools that are safe to run headless and belong to a scope
    # the user can pre-authorize.
    if tool.scope is None:
        raise ValidationAppError("This tool cannot be used in automations.")
    try:
        tool.params_model.model_validate(params or {})
    except Exception as exc:
        raise ValidationAppError(f"Invalid action params: {str(exc)[:200]}")


@router.get("")
def list_automations(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    rows = db.execute(
        select(Automation).where(Automation.user_id == user.id)
        .order_by(Automation.created_at.desc()).limit(200)
    ).scalars().all()
    return {"automations": [_automation_json(a) for a in rows]}


@router.post("", status_code=201)
def create_automation(
    body: AutomationIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    user_settings = ensure_user_settings(db, user.id)
    if user_settings.emergency_stop:
        raise ForbiddenError("Emergency stop is active — automations cannot be created.")

    _validate_action(body.action_tool, body.action_params)
    next_run = _compute_next_run(body.trigger_type, body.trigger_config)

    # Enabling an automation REQUIRES the user to hold an explicit standing
    # grant for the tool's scope (deliberate pre-authorization).
    if body.enabled:
        tool = tool_registry.get(body.action_tool)
        firewall = PermissionFirewall(db)
        grants = {g.scope for g in firewall.list_grants(user) if g.allowed}
        if tool.scope not in grants:
            raise ForbiddenError(
                f"To enable an automation using '{tool.name}', first grant the "
                f"'{tool.scope}' permission in Security settings."
            )

    a = Automation(
        user_id=user.id, name=body.name.strip(), description=body.description,
        enabled=body.enabled, trigger_type=body.trigger_type,
        trigger_config=body.trigger_config, action_tool=body.action_tool,
        action_params=body.action_params, max_retries=body.max_retries,
        next_run_at=next_run if body.enabled else None,
    )
    db.add(a)
    audit(db, event_type="automation_created", category="automation",
          action=f"Automation created: {a.name[:100]} (enabled={a.enabled})",
          user_id=user.id, resource=a.id, request_id=request.state.request_id,
          detail={"tool": a.action_tool})
    db.commit()
    return {"automation": _automation_json(a)}


@router.patch("/{automation_id}")
def update_automation(
    automation_id: str, body: AutomationPatch, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    user_settings = ensure_user_settings(db, user.id)
    a = db.get(Automation, automation_id)
    if a is None or a.user_id != user.id:
        raise NotFoundError("Automation not found.")
    if body.name is not None:
        a.name = body.name.strip()
    if body.description is not None:
        a.description = body.description
    if body.trigger_config is not None:
        a.trigger_config = body.trigger_config
        a.next_run_at = _compute_next_run(a.trigger_type, a.trigger_config, last_run=a.last_run_at) if a.enabled else None
    if body.action_params is not None:
        _validate_action(a.action_tool, body.action_params)
        a.action_params = body.action_params
    if body.max_retries is not None:
        a.max_retries = body.max_retries
    if body.enabled is not None:
        if body.enabled:
            if user_settings.emergency_stop:
                raise ForbiddenError("Emergency stop is active.")
            tool = tool_registry.get(a.action_tool)
            firewall = PermissionFirewall(db)
            grants = {g.scope for g in firewall.list_grants(user) if g.allowed}
            if tool.scope not in grants:
                raise ForbiddenError(
                    f"Grant the '{tool.scope}' permission in Security settings before enabling."
                )
            a.enabled = True
            a.next_run_at = _compute_next_run(a.trigger_type, a.trigger_config, last_run=a.last_run_at)
        else:
            a.enabled = False
            a.next_run_at = None
    audit(db, event_type="automation_updated", category="automation",
          action=f"Automation updated: {a.name[:100]} (enabled={a.enabled})",
          user_id=user.id, resource=a.id, request_id=request.state.request_id)
    db.commit()
    return {"automation": _automation_json(a)}


@router.delete("/{automation_id}")
def delete_automation(
    automation_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    a = db.get(Automation, automation_id)
    if a is None or a.user_id != user.id:
        raise NotFoundError("Automation not found.")
    db.delete(a)
    audit(db, event_type="automation_deleted", category="automation",
          action=f"Automation deleted: {a.name[:100]}", user_id=user.id,
          resource=a.id, request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


@router.get("/{automation_id}/runs")
def automation_runs(
    automation_id: str,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    a = db.get(Automation, automation_id)
    if a is None or a.user_id != user.id:
        raise NotFoundError("Automation not found.")
    rows = db.execute(
        select(AutomationRun)
        .where(AutomationRun.automation_id == automation_id)
        .order_by(AutomationRun.started_at.desc()).limit(100)
    ).scalars().all()
    return {"runs": [
        {
            "id": r.id, "status": r.status, "attempt": r.attempt,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "result": r.result, "error": r.error,
        } for r in rows
    ]}
