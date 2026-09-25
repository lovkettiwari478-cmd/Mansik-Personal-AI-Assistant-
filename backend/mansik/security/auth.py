"""Authentication & authorization dependencies.

Design:
- Server-side sessions; the cookie carries an opaque random token
  (secrets.token_urlsafe(32)). Only its SHA-256 hash is stored.
- Cookie: HttpOnly + SameSite=Lax + Secure (configurable).
- CSRF: double-submit token. A non-HttpOnly ``mansik_csrf`` cookie holds a
  random token; every unsafe (non-GET) request must echo it in the
  ``X-CSRF-Token`` header. SameSite=Lax already blocks cross-site POSTs;
  this adds defence in depth.
- Sessions are revoked server-side; revocation is effective immediately.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..database import db_session
from ..errors import AuthError, ForbiddenError
from ..models import AuthSession, User, UserSettings, new_id, utcnow
from ..observability import audit

SESSION_COOKIE = "mansik_session"
CSRF_COOKIE = "mansik_csrf"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: DbSession, user: User, *, ip: str = "", user_agent: str = "") -> tuple[AuthSession, str]:
    """Creates a session; returns (session_row, raw_cookie_token)."""
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = utcnow()
    session = AuthSession(
        id=new_id(),
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=csrf_token,
        ip=(ip or "")[:64],
        user_agent=(user_agent or "")[:255],
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    return session, raw_token


def resolve_session(db: DbSession, raw_token: str | None) -> tuple[User, AuthSession] | None:
    if not raw_token:
        return None
    now = utcnow()
    stmt = (
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            User.is_active.is_(True),
        )
    )
    row = db.execute(stmt).first()
    if row is None:
        return None
    session, user = row
    session.last_seen_at = now
    return user, session


def get_request_session(request: Request) -> tuple[User, AuthSession] | None:
    raw = request.cookies.get(SESSION_COOKIE)
    db = db_session()
    try:
        found = resolve_session(db, raw)
        if found:
            db.commit()
        return found
    finally:
        db.close()


def get_db() -> DbSession:
    """FastAPI dependency yielding a request-scoped DB session."""
    session = db_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _client_ip(request: Request) -> str:
    # The preview proxy / reverse proxy provides X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def require_auth(request: Request, db: DbSession = Depends(get_db)) -> tuple[User, AuthSession]:
    """Dependency: valid session + CSRF check for unsafe methods."""
    raw = request.cookies.get(SESSION_COOKIE)
    found = resolve_session(db, raw)
    if found is None:
        raise AuthError("Authentication required.")
    user, session = found

    if request.method not in SAFE_METHODS:
        header_token = request.headers.get("x-csrf-token", "")
        if not header_token or not secrets.compare_digest(header_token, session.csrf_token):
            audit(db, event_type="csrf_rejected", category="security", action="CSRF token missing/invalid",
                  user_id=user.id, ip=_client_ip(request),
                  user_agent=request.headers.get("user-agent", ""), request_id=request.state.request_id)
            raise ForbiddenError("CSRF validation failed. Refresh the page and try again.")

    db.commit()
    request.state.user = user
    request.state.session = session
    request.state.db = db
    return user, session


def ensure_user_settings(db: DbSession, user_id: str) -> UserSettings:
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    settings = db.execute(stmt).scalar_one_or_none()
    if settings is None:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        db.flush()
    return settings


def set_session_cookies(response, raw_token: str, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE, raw_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=False,  # must be readable by the SPA for double-submit
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def clear_session_cookies(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
