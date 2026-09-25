"""Security boundary tests: CSRF, IDOR/user isolation, headers, rate
limits, secret leakage, auth bypass."""

from __future__ import annotations

from conftest import csrf_headers


def test_csrf_required_for_unsafe_methods(auth_client):
    # no token
    r = auth_client.post("/api/memories", json={"content": "no csrf token here"})
    assert r.status_code == 403
    # wrong token
    r = auth_client.post("/api/memories", json={"content": "bad token"},
                         headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    # correct token
    r = auth_client.post("/api/memories", json={"content": "with csrf token"},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 201


def test_csrf_not_required_for_get(auth_client):
    assert auth_client.get("/api/memories").status_code == 200


def test_unauthenticated_access_denied(client):
    for path, method in [
        ("/api/memories", "GET"), ("/api/tasks", "GET"), ("/api/calendar", "GET"),
        ("/api/activity", "GET"), ("/api/automations", "GET"), ("/api/files", "GET"),
        ("/api/settings", "GET"), ("/api/security/permissions", "GET"),
        ("/api/tools", "GET"), ("/api/notifications", "GET"), ("/api/status", "GET"),
        ("/api/confirmations/pending", "GET"), ("/api/conversations", "GET"),
        ("/api/graph/entities", "GET"), ("/api/integrations", "GET"),
        ("/api/chat", "POST"),
    ]:
        r = client.request(method, path)
        assert r.status_code == 401, f"{method} {path} returned {r.status_code}"


def test_user_isolation_idor(auth_client, second_client):
    """User B must never see or mutate user A's resources."""
    # A creates resources of each type
    mem = auth_client.post("/api/memories", json={"content": "A's private memory"},
                           headers=csrf_headers(auth_client)).json()["memory"]
    task = auth_client.post("/api/tasks", json={"title": "A's private task"},
                            headers=csrf_headers(auth_client)).json()["task"]
    event = auth_client.post("/api/calendar", json={
        "title": "A's private event", "starts_at": "2027-01-01T10:00:00+00:00",
        "ends_at": "2027-01-01T11:00:00+00:00"}, headers=csrf_headers(auth_client)).json()["event"]
    chat = auth_client.post("/api/chat", json={"message": "what time is it"},
                            headers=csrf_headers(auth_client))
    convo_id = None
    for line in chat.text.split("\n\n"):
        if line.startswith("data: ") and '"event": "done"' in line:
            import json
            convo_id = json.loads(line[6:])["conversation_id"]
    assert convo_id
    auto = auth_client.post("/api/automations", json={
        "name": "A's automation", "trigger_type": "interval",
        "trigger_config": {"every_seconds": 3600}, "action_tool": "notify.user",
        "action_params": {"title": "hi"}}, headers=csrf_headers(auth_client)).json()["automation"]

    b_headers = csrf_headers(second_client)
    # B cannot read A's resources
    assert second_client.get(f"/api/conversations/{convo_id}/messages").status_code == 404
    assert second_client.get(f"/api/conversations/{convo_id}").status_code in (404, 405)
    # B cannot mutate or delete A's resources
    assert second_client.patch(f"/api/memories/{mem['id']}", json={"content": "hijack"},
                               headers=b_headers).status_code == 404
    assert second_client.delete(f"/api/memories/{mem['id']}", headers=b_headers).status_code == 404
    assert second_client.patch(f"/api/tasks/{task['id']}", json={"title": "hijack"},
                               headers=b_headers).status_code == 404
    assert second_client.delete(f"/api/tasks/{task['id']}", headers=b_headers).status_code == 404
    assert second_client.delete(f"/api/calendar/{event['id']}", headers=b_headers).status_code == 404
    assert second_client.delete(f"/api/automations/{auto['id']}", headers=b_headers).status_code == 404
    # B's listings don't include A's data
    assert all(m["id"] != mem["id"] for m in second_client.get("/api/memories").json()["memories"])
    assert all(t["id"] != task["id"] for t in second_client.get("/api/tasks").json()["tasks"])
    assert all(e["id"] != event["id"] for e in second_client.get("/api/calendar").json()["events"])
    assert all(c["id"] != convo_id for c in second_client.get("/api/conversations").json()["conversations"])
    # B cannot chat into A's conversation
    r = second_client.post("/api/chat", json={"conversation_id": convo_id, "message": "inject"},
                           headers=b_headers)
    assert r.status_code == 404
    # B's activity log contains no A audit rows
    acts = second_client.get("/api/activity?limit=500").json()["activity"]
    assert all(a.get("user_id") != auth_client.user["id"] for a in acts)


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert r.headers.get("X-Request-ID")


def test_secure_cookie_flags(tmp_path, monkeypatch):
    from conftest import make_client
    c = make_client(tmp_path, monkeypatch, MANISK_COOKIE_SECURE="true")
    r = c.post("/api/auth/register", json={
        "email": "secure@example.com", "password": "Str0ngPass!123", "display_name": "S"})
    set_cookie = r.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie.lower()


def test_rate_limiting_on_login(tmp_path, monkeypatch):
    from conftest import make_client
    c = make_client(tmp_path, monkeypatch,
                    MANISK_RATE_LIMIT_ENABLED="true", MANISK_RATE_LIMIT_AUTH_PER_MINUTE="5")
    codes = []
    for _ in range(7):
        r = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "WhateverPass1"})
        codes.append(r.status_code)
    assert 429 in codes
    assert codes.count(429) >= 2


def test_secrets_never_leaked(tmp_path, monkeypatch):
    from conftest import make_client
    c = make_client(tmp_path, monkeypatch,
                    MANISK_AI_BASE_URL="https://api.example.com/v1",
                    MANISK_AI_API_KEY="sk-super-secret-key-123",
                    MANISK_AI_MODEL="test-model",
                    MANISK_SESSION_SECRET="master-secret-xyz")
    c.post("/api/auth/register", json={
        "email": "leak@example.com", "password": "Str0ngPass!123", "display_name": "L"})
    for path in ("/api/status", "/api/tools", "/api/integrations", "/api/health",
                 "/api/settings", "/api/security/permissions"):
        body = c.get(path).text
        assert "sk-super-secret-key-123" not in body, path
        assert "master-secret-xyz" not in body, path


def test_error_responses_are_safe(auth_client):
    """No stack traces in user-facing errors."""
    r = auth_client.get("/api/conversations/nonexistent-id-xyz/messages")
    assert r.status_code == 404
    body = r.text.lower()
    assert "traceback" not in body
    assert ".py" not in body


def test_validation_rejects_unknown_fields(auth_client):
    r = auth_client.post("/api/memories",
                         json={"content": "valid content", "hack": "extra field"},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 422


def test_sql_injection_attempts_are_safe(auth_client):
    payload = "'; DROP TABLE users; --"
    r = auth_client.post("/api/memories", json={"content": payload},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 201
    r = auth_client.post("/api/memories/search", json={"query": payload},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 200
    assert auth_client.get("/api/auth/me").status_code == 200  # users table intact
