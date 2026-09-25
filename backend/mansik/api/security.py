"""Security center endpoints — permission scopes, grants, emergency stop."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..errors import NotFoundError, ValidationAppError
from ..models import AuthSession, User, UserSettings, utcnow
from ..observability import audit
from ..permissions import SCOPES, PermissionFirewall
from ..security.auth import ensure_user_settings, get_db, require_auth
from .schemas import EmergencyStopIn, GrantIn

router = APIRouter(prefix="/api/security", tags=["security"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


@router.get("/permissions")
def permissions(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    firewall = PermissionFirewall(db)
    grants = {g.scope: g for g in firewall.list_grants(user)}
    out = []
    for key, scope in SCOPES.items():
        g = grants.get(key)
        out.append({
            "scope": key, "label": scope.label, "description": scope.description,
            "risk": scope.risk,
            "granted": bool(g and g.allowed),
            "denied": bool(g and not g.allowed),
            "expires_at": g.expires_at.isoformat() if g and g.expires_at else None,
            "note": g.note if g else "",
        })
    return {"permissions": out}


@router.post("/permissions")
def set_grant(
    body: GrantIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    firewall = PermissionFirewall(db)
    grant = firewall.set_grant(
        user=user, scope=body.scope, allowed=body.allowed, note=body.note,
        request_id=request.state.request_id, ip=_client_ip(request),
    )
    db.commit()
    return {"ok": True, "scope": grant.scope, "allowed": grant.allowed}


@router.delete("/permissions/{scope}")
def revoke_grant(
    scope: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    firewall = PermissionFirewall(db)
    firewall.revoke_grant(user=user, scope=scope,
                          request_id=request.state.request_id, ip=_client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/emergency-stop")
def emergency_stop_status(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    settings = ensure_user_settings(db, user.id)
    return {
        "active": settings.emergency_stop,
        "since": settings.emergency_stop_at.isoformat() if settings.emergency_stop_at else None,
    }


@router.post("/emergency-stop")
def set_emergency_stop(
    body: EmergencyStopIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    settings = ensure_user_settings(db, user.id)
    settings.emergency_stop = body.enabled
    settings.emergency_stop_at = utcnow() if body.enabled else None
    audit(db, event_type="emergency_stop" if body.enabled else "emergency_stop_released",
          category="security",
          action=f"Emergency stop {'ACTIVATED' if body.enabled else 'released'}",
          user_id=user.id, ip=_client_ip(request), request_id=request.state.request_id)
    db.commit()
    return {"active": settings.emergency_stop}
