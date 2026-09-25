"""Database engine and session management.

SQLite is used by default (WAL mode, foreign keys enforced). PostgreSQL is
supported in production via MANISK_DATABASE_URL (same models, Alembic
migrations).
"""

from __future__ import annotations

import contextlib
import threading
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_local = threading.local()


def _make_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    # Normalize provider-injected URLs for SQLAlchemy 2.x:
    # Render/Heroku style `postgres://` (and bare `postgresql://`) → psycopg2.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
    return engine


_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_engine_lock = threading.Lock()


def get_engine() -> Engine:
    global _engine, _session_factory
    with _engine_lock:
        if _engine is None:
            _engine = _make_engine()
            _session_factory = sessionmaker(
                bind=_engine, autoflush=False, expire_on_commit=False, future=True
            )
        return _engine


def reset_engine() -> None:
    """Used by tests to swap the database."""
    global _engine, _session_factory
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager yielding a session with commit/rollback handling."""
    get_engine()
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_session() -> Session:
    """Plain session for manual lifecycle management."""
    get_engine()
    return _session_factory()


def is_postgres() -> bool:
    return get_settings().database_url.startswith("postgresql")
