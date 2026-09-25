"""Test fixtures — fresh database + app per test.

Test doubles (e.g. a fake search backend) are used ONLY inside tests to
exercise flows deterministically; the application code itself never fakes
external services.
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BACKEND_DIR)


def make_client(tmp_path, monkeypatch, **overrides) -> TestClient:
    from mansik.config import get_settings
    from mansik.database import reset_engine
    from mansik.main import create_app
    from mansik.security.rate_limit import limiter

    env = {
        "MANISK_DATABASE_URL": f"sqlite:///{tmp_path}/test.db",
        "MANISK_STORAGE_DIR": str(tmp_path / "files"),
        "MANISK_COOKIE_SECURE": "false",
        "MANISK_RATE_LIMIT_ENABLED": "false",
        "MANISK_SCHEDULER_ENABLED": "false",
        "MANISK_ENVIRONMENT": "test",
    }
    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    reset_engine()
    limiter.reset()

    app = create_app()
    client = TestClient(app)
    client.__enter__()  # run lifespan (migrations)
    client._tmp_path = tmp_path
    return client


@pytest.fixture
def client(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def auth_client(client):
    """A client with a registered+logged-in user + CSRF helper."""
    import secrets as _secrets

    email = f"user-{_secrets.token_hex(4)}@example.com"
    r = client.post("/api/auth/register", json={
        "email": email, "password": "Str0ngPass!123", "display_name": "Test User",
    })
    assert r.status_code == 201, r.text
    csrf = client.cookies.get("mansik_csrf")
    client.csrf = csrf
    client.email = email
    client.user = r.json()["user"]
    return client


@pytest.fixture
def second_client(tmp_path, monkeypatch):
    """A second, fully isolated user on the SAME app instance."""
    # Reuse the first client's database by reconstructing with same env vars
    import secrets as _secrets
    from mansik.config import get_settings
    from mansik.database import get_engine
    from mansik.main import create_app
    from mansik.security.rate_limit import limiter

    url = get_settings().database_url
    storage = get_settings().storage_dir
    monkeypatch.setenv("MANISK_DATABASE_URL", url)
    monkeypatch.setenv("MANISK_STORAGE_DIR", storage)
    monkeypatch.setenv("MANISK_COOKIE_SECURE", "false")
    monkeypatch.setenv("MANISK_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("MANISK_SCHEDULER_ENABLED", "false")
    app = create_app()
    c2 = TestClient(app)
    c2.__enter__()
    limiter.reset()
    email = f"user2-{_secrets.token_hex(4)}@example.com"
    r = c2.post("/api/auth/register", json={
        "email": email, "password": "AnotherStr0ng!456", "display_name": "Second User",
    })
    assert r.status_code == 201, r.text
    c2.csrf = c2.cookies.get("mansik_csrf")
    c2.email = email
    c2.user = r.json()["user"]
    return c2


def csrf_headers(client):
    return {"X-CSRF-Token": getattr(client, "csrf", None) or client.cookies.get("mansik_csrf")}


def sse_events(response):
    """Parse an SSE stream body into event dicts."""
    import json
    events = []
    for chunk in response.text.strip().split("\n\n"):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events
