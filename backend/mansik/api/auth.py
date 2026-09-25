"""Authentication endpoints.

- Register/login are rate-limited per IP.
- Sessions are opaque server-side tokens; cookie-based.
- All auth events are audited.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..errors import AuthError, ConflictError, ForbiddenError, NotFoundError, RateLimitError
from ..models import AuthSession, User, UserSettings, utcnow
from ..observability import audit, get_logger, log
from ..security import passwords
from ..security.auth import (
    clear_session_cookies, create_session, ensure_user_settings, get_db,
    require_auth, set_session_cookies,
)
from ..security.rate_limit import limiter
from .schemas import ChangePasswordIn, LoginIn, RegisterIn

logger = get_logger("mansik.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _rate_limit(request: Request, bucket: str) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    ip = _client_ip(request)
    allowed, retry = limiter.hit(f"{bucket}:{ip}", settings.rate_limit_auth_per_minute, 60)
    if not allowed:
        raise RateLimitError(f"Too many attempts. Try again in {retry:.0f}s.", detail={"retry_after": round(retry)})


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    _rate_limit(request, "register")
    email = body.email.lower().strip()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        audit(db, event_type="register_duplicate", category="auth", action="Registration with existing email",
              resource=email, ip=_client_ip(request), request_id=request.state.request_id)
        raise ConflictError("An account with this email already exists.")

    policy_error = passwords.password_policy_error(body.password)
    if policy_error:
        raise ForbiddenError(policy_error)

    user = User(
        email=email,
        password_hash=passwords.hash_password(body.password),
        display_name=body.display_name.strip(),
    )
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    session, raw_token = create_session(
        db, user, ip=_client_ip(request), user_agent=request.headers.get("user-agent", "")
    )
    audit(db, event_type="register", category="auth", action="Account created", user_id=user.id,
          resource=email, ip=_client_ip(request), user_agent=request.headers.get("user-agent", ""),
          request_id=request.state.request_id)
    db.commit()
    set_session_cookies(response, raw_token, session.csrf_token)
    return {"user": user.public()}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    _rate_limit(request, "login")
    email = body.email.lower().strip()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    # Constant-shape failure: never reveal whether the account exists.
    ok = bool(user) and user.is_active and passwords.verify_password(body.password, user.password_hash)
    if not ok:
        audit(db, event_type="login_failed", category="auth", action="Failed login",
              resource=email, ip=_client_ip(request), request_id=request.state.request_id)
        raise AuthError("Invalid email or password.")

    session, raw_token = create_session(
        db, user, ip=_client_ip(request), user_agent=request.headers.get("user-agent", "")
    )
    user.last_login_at = utcnow()
    audit(db, event_type="login", category="auth", action="Login", user_id=user.id,
          ip=_client_ip(request), user_agent=request.headers.get("user-agent", ""),
          request_id=request.state.request_id)
    db.commit()
    set_session_cookies(response, raw_token, session.csrf_token)
    return {"user": user.public()}


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    user_session = None
    raw = request.cookies.get("mansik_session")
    if raw:
        from ..security.auth import hash_token, resolve_session
        found = resolve_session(db, raw)
        if found:
            user, user_session = found
            user_session.revoked_at = utcnow()
            audit(db, event_type="logout", category="auth", action="Logout", user_id=user.id,
                  ip=_client_ip(request), request_id=request.state.request_id)
            db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(auth: tuple[User, AuthSession] = Depends(require_auth)):
    user, _ = auth
    return {"user": user.public()}


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    if not passwords.verify_password(body.current_password, user.password_hash):
        audit(db, event_type="password_change_failed", category="security",
              action="Wrong current password", user_id=user.id, ip=_client_ip(request),
              request_id=request.state.request_id)
        raise AuthError("Current password is incorrect.")
    policy_error = passwords.password_policy_error(body.new_password)
    if policy_error:
        raise ForbiddenError(policy_error)
    user.password_hash = passwords.hash_password(body.new_password)
    # Revoke all other sessions after a password change.
    other = db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.id != auth[1].id,
        )
    ).scalars().all()
    for s in other:
        s.revoked_at = utcnow()
    audit(db, event_type="password_changed", category="security", action="Password changed",
          user_id=user.id, ip=_client_ip(request), request_id=request.state.request_id,
          detail={"sessions_revoked": len(other)})
    db.commit()
    return {"ok": True, "sessions_revoked": len(other)}


@router.get("/sessions")
def list_sessions(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, current = auth
    rows = db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        ).order_by(AuthSession.last_seen_at.desc())
    ).scalars().all()
    return {"sessions": [
        {
            "id": s.id, "created_at": s.created_at.isoformat(),
            "last_seen_at": s.last_seen_at.isoformat(), "expires_at": s.expires_at.isoformat(),
            "ip": s.ip, "user_agent": s.user_agent[:120],
            "current": s.id == current.id,
        } for s in rows
    ]}


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, current = auth
    target = db.get(AuthSession, session_id)
    if target is None or target.user_id != user.id:  # IDOR guard
        raise NotFoundError("Session not found.")
    target.revoked_at = utcnow()
    audit(db, event_type="session_revoked", category="security", action="Session revoked",
          user_id=user.id, resource=session_id, ip=_client_ip(request),
          request_id=request.state.request_id)
    db.commit()
    return {"ok": True, "was_current": target.id == current.id}


@router.post("/logout-all")
def logout_all(
    request: Request, response: Response,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    rows = db.execute(
        select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
    ).scalars().all()
    for s in rows:
        s.revoked_at = utcnow()
    audit(db, event_type="logout_all", category="security", action="All sessions revoked",
          user_id=user.id, ip=_client_ip(request), request_id=request.state.request_id,
          detail={"count": len(rows)})
    db.commit()
    clear_session_cookies(response)
    return {"ok": True, "revoked": len(rows)}
