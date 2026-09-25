"""The MANISK permission firewall.

Every sensitive action passes through ``PermissionFirewall.check`` before
execution. The firewall distinguishes:

- READ actions — always allowed for the authenticated owner.
- LOW_RISK_WRITE — allowed unless explicitly denied (mutations of the
  user's own tasks/memory/calendar).
- HIGH_RISK_WRITE / EXTERNAL_COMMUNICATION / FINANCIAL / SECURITY /
  DEVICE_CONTROL — require either (a) an explicit standing grant the user
  created deliberately, or (b) a fresh, single-use confirmation.

An active emergency stop blocks everything except READ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..config import (
    RISK_DEVICE, RISK_EXTERNAL_COMM, RISK_FINANCIAL, RISK_HIGH_WRITE,
    RISK_LOW_WRITE, RISK_READ, RISK_SECURITY, get_settings,
)
from ..errors import ForbiddenError, NotFoundError
from ..models import Confirmation, PermissionGrant, User, UserSettings, new_id, utcnow
from ..observability import audit

CONFIRMATION_RISKS = {
    RISK_HIGH_WRITE, RISK_EXTERNAL_COMM, RISK_FINANCIAL, RISK_SECURITY, RISK_DEVICE,
}


@dataclass
class Decision:
    allowed: bool
    needs_confirmation: bool = False
    confirmation_id: str | None = None
    risk: str = RISK_READ
    scope: str | None = None
    reason: str = ""
    standing_grant: bool = False
    detail: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "allowed": self.allowed,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_id": self.confirmation_id,
            "risk": self.risk,
            "scope": self.scope,
            "reason": self.reason,
            "standing_grant": self.standing_grant,
        }


def _active_grant(db: DbSession, user_id: str, scope: str) -> PermissionGrant | None:
    stmt = select(PermissionGrant).where(
        PermissionGrant.user_id == user_id,
        PermissionGrant.scope == scope,
    )
    grant = db.execute(stmt).scalar_one_or_none()
    if grant is None:
        return None
    if grant.expires_at is not None and grant.expires_at <= utcnow():
        return None
    return grant


class PermissionFirewall:
    def __init__(self, db: DbSession):
        self.db = db

    # -- public API ----------------------------------------------------------

    def check(
        self,
        *,
        user: User,
        user_settings: UserSettings,
        tool_id: str,
        tool_name: str,
        risk: str,
        scope: str | None,
        params: dict,
        conversation_id: str | None = None,
        reason: str = "",
        request_id: str = "",
        ip: str = "",
    ) -> Decision:
        # 1) Emergency stop blocks all non-read actions immediately.
        if user_settings.emergency_stop and risk != RISK_READ:
            audit(self.db, event_type="firewall_blocked", category="security",
                  action="Emergency stop active — action blocked",
                  user_id=user.id, resource=tool_id, request_id=request_id, ip=ip,
                  detail={"risk": risk, "scope": scope})
            return Decision(
                allowed=False, risk=risk, scope=scope,
                reason="Emergency stop is active — all actions are halted until you disable it in Security settings.",
            )

        # 2) Reads are always fine for the owner.
        if risk == RISK_READ:
            return Decision(allowed=True, risk=risk, scope=scope)

        # 3) Scope resolution.
        if scope:
            grant = _active_grant(self.db, user.id, scope)
            if grant is not None and not grant.allowed:
                audit(self.db, event_type="firewall_blocked", category="security",
                      action=f"Scope '{scope}' denied by user",
                      user_id=user.id, resource=tool_id, request_id=request_id, ip=ip)
                return Decision(
                    allowed=False, risk=risk, scope=scope,
                    reason=f"'{scope}' is denied for your account. Re-enable it in Security settings.",
                )

        # 4) Risk gate.
        if risk in CONFIRMATION_RISKS:
            if scope and grant is not None and grant.allowed:
                # Explicit standing grant the user created deliberately.
                audit(self.db, event_type="firewall_allowed", category="security",
                      action=f"Standing grant used for '{scope}'",
                      user_id=user.id, resource=tool_id, request_id=request_id, ip=ip)
                return Decision(allowed=True, risk=risk, scope=scope, standing_grant=True)

            # Requires a fresh confirmation unless a standing grant exists.
            settings = get_settings()
            confirmation = Confirmation(
                id=new_id(),
                user_id=user.id,
                conversation_id=conversation_id,
                tool_id=tool_id,
                params=params,
                risk=risk,
                reason=reason or f"{tool_name} requires confirmation ({risk.replace('_', ' ')}).",
                created_at=utcnow(),
                expires_at=utcnow() + timedelta(minutes=settings.confirmation_ttl_minutes),
            )
            self.db.add(confirmation)
            self.db.flush()
            audit(self.db, event_type="confirmation_requested", category="security",
                  action=f"Confirmation requested for {tool_id}",
                  user_id=user.id, resource=tool_id, request_id=request_id, ip=ip,
                  detail={"confirmation_id": confirmation.id, "risk": risk, "scope": scope})
            return Decision(
                allowed=False, needs_confirmation=True,
                confirmation_id=confirmation.id, risk=risk, scope=scope,
                reason=confirmation.reason,
                detail={"tool": tool_name, "params": params},
            )

        # 5) LOW_RISK_WRITE — allowed by default, audited.
        return Decision(allowed=True, risk=risk, scope=scope)

    # -- confirmation lifecycle ----------------------------------------------

    def approve_confirmation(
        self, *, user: User, confirmation_id: str, request_id: str = "", ip: str = "",
    ) -> Confirmation:
        confirmation = self._load_pending(user.id, confirmation_id)
        confirmation.status = "approved"
        confirmation.decided_at = utcnow()
        audit(self.db, event_type="confirmation_approved", category="security",
              action=f"User approved {confirmation.tool_id}",
              user_id=user.id, resource=confirmation.tool_id, request_id=request_id, ip=ip,
              detail={"confirmation_id": confirmation.id})
        return confirmation

    def deny_confirmation(
        self, *, user: User, confirmation_id: str, request_id: str = "", ip: str = "",
    ) -> Confirmation:
        confirmation = self._load_pending(user.id, confirmation_id)
        confirmation.status = "denied"
        confirmation.decided_at = utcnow()
        audit(self.db, event_type="confirmation_denied", category="security",
              action=f"User denied {confirmation.tool_id}",
              user_id=user.id, resource=confirmation.tool_id, request_id=request_id, ip=ip,
              detail={"confirmation_id": confirmation.id})
        return confirmation

    def _load_pending(self, user_id: str, confirmation_id: str) -> Confirmation:
        # User isolation: confirmation must belong to the requesting user.
        confirmation = self.db.get(Confirmation, confirmation_id)
        if confirmation is None or confirmation.user_id != user_id:
            raise NotFoundError("Confirmation not found.")  # IDOR-safe: 404
        if confirmation.status != "pending":
            raise ForbiddenError(f"Confirmation already {confirmation.status}.")
        if confirmation.expires_at <= utcnow():
            confirmation.status = "expired"
            raise ForbiddenError("Confirmation expired — ask again if you still want this.")
        return confirmation

    # -- standing grants -----------------------------------------------------

    def set_grant(
        self, *, user: User, scope: str, allowed: bool,
        expires_at=None, note: str = "", request_id: str = "", ip: str = "",
    ) -> PermissionGrant:
        from .scopes import SCOPES

        if scope not in SCOPES:
            raise ForbiddenError("Unknown scope.")
        grant = _active_grant(self.db, user.id, scope)
        inactive = self.db.execute(
            select(PermissionGrant).where(
                PermissionGrant.user_id == user.id, PermissionGrant.scope == scope
            )
        ).scalar_one_or_none()
        grant = inactive
        if grant is None:
            grant = PermissionGrant(user_id=user.id, scope=scope)
            self.db.add(grant)
        grant.allowed = allowed
        grant.expires_at = expires_at
        grant.note = note[:300]
        audit(self.db, event_type="grant_changed", category="security",
              action=f"Scope '{scope}' set to {'allowed' if allowed else 'denied'}",
              user_id=user.id, resource=scope, request_id=request_id, ip=ip)
        return grant

    def revoke_grant(self, *, user: User, scope: str, request_id: str = "", ip: str = "") -> None:
        grant = self.db.execute(
            select(PermissionGrant).where(
                PermissionGrant.user_id == user.id, PermissionGrant.scope == scope
            )
        ).scalar_one_or_none()
        if grant is not None:
            self.db.delete(grant)
        audit(self.db, event_type="grant_revoked", category="security",
              action=f"Scope '{scope}' revoked", user_id=user.id, resource=scope,
              request_id=request_id, ip=ip)

    def list_grants(self, user: User) -> list[PermissionGrant]:
        return list(self.db.execute(
            select(PermissionGrant).where(PermissionGrant.user_id == user.id)
        ).scalars())
