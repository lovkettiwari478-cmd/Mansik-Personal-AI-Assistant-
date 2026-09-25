"""Permission firewall tests — the core MANISK security system."""

from __future__ import annotations

import json

from conftest import csrf_headers


def _events(response):
    events = []
    for chunk in response.text.strip().split("\n\n"):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events


def test_external_action_requires_confirmation(auth_client):
    """web.search is EXTERNAL_COMMUNICATION → must not run without approval."""
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "search the web for quantum computing"},
                         headers=h)
    assert r.status_code == 200
    events = _events(r)
    kinds = [e["event"] for e in events]
    assert "confirmation_required" in kinds
    conf = [e for e in events if e["event"] == "confirmation_required"][0]
    assert conf["risk"] == "external_communication"
    # no tool_end with success — the tool did NOT execute
    tool_ends = [e for e in events if e["event"] == "tool_end"]
    assert not any(e.get("success") for e in tool_ends)


def test_confirmation_appears_in_pending_list(auth_client):
    h = csrf_headers(auth_client)
    auth_client.post("/api/chat", json={"message": "search the web for cats"}, headers=h)
    r = auth_client.get("/api/confirmations/pending")
    assert r.status_code == 200
    assert len(r.json()["confirmations"]) >= 1


def test_confirmation_denial_blocks_execution(auth_client, monkeypatch):
    h = csrf_headers(auth_client)
    # test double: search backend succeeds (labels: test-only)
    async def fake_search(query):
        return [{"title": "Result", "url": "https://example.com", "snippet": "s"}]
    monkeypatch.setattr("mansik.tools.web_tools._duckduckgo_search", fake_search)

    events = _events(auth_client.post("/api/chat", json={"message": "search the web for cats"}, headers=h))
    conf = [e for e in events if e["event"] == "confirmation_required"][0]
    cid = conf["confirmation_id"]

    r = auth_client.post(f"/api/confirmations/{cid}/deny", headers=h)
    assert r.status_code == 200
    assert r.json()["confirmation"]["status"] == "denied"

    # a denied confirmation cannot be reused
    r = auth_client.post(f"/api/confirmations/{cid}/approve", headers=h)
    assert r.status_code == 403


def test_confirmation_approval_executes_once(auth_client, monkeypatch):
    h = csrf_headers(auth_client)
    calls = []

    async def fake_search(query):
        calls.append(query)
        return [{"title": "Cats", "url": "https://example.com/cats", "snippet": "all about cats"}]
    monkeypatch.setattr("mansik.tools.web_tools._duckduckgo_search", fake_search)

    events = _events(auth_client.post("/api/chat", json={"message": "search the web for cats"}, headers=h))
    conf = [e for e in events if e["event"] == "confirmation_required"][0]
    cid = conf["confirmation_id"]

    r = auth_client.post(f"/api/confirmations/{cid}/approve", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["success"] is True
    assert "Cats" in json.dumps(body["result"])
    assert len(calls) == 1

    # single-use: second approve fails
    r = auth_client.post(f"/api/confirmations/{cid}/approve", headers=h)
    assert r.status_code == 403

    # the action was audited
    acts = auth_client.get("/api/activity?limit=50").json()["activity"]
    assert any(a["event_type"] in ("confirmation_approved", "tool_executed") for a in acts)


def test_confirmation_isolated_between_users(auth_client, second_client):
    h = csrf_headers(auth_client)
    events = _events(auth_client.post("/api/chat", json={"message": "search the web for cats"}, headers=h))
    cid = [e for e in events if e["event"] == "confirmation_required"][0]["confirmation_id"]
    # second user cannot approve or deny user A's confirmation
    r = second_client.post(f"/api/confirmations/{cid}/approve", headers=csrf_headers(second_client))
    assert r.status_code == 404
    r = second_client.post(f"/api/confirmations/{cid}/deny", headers=csrf_headers(second_client))
    assert r.status_code == 404


def test_standing_grant_skips_confirmation(auth_client, monkeypatch):
    h = csrf_headers(auth_client)
    async def fake_search(query):
        return [{"title": "R", "url": "https://example.com", "snippet": "s"}]
    monkeypatch.setattr("mansik.tools.web_tools._duckduckgo_search", fake_search)

    # grant the scope persistently
    r = auth_client.post("/api/security/permissions",
                         json={"scope": "tools:web", "allowed": True, "note": "test grant"},
                         headers=h)
    assert r.status_code == 200

    events = _events(auth_client.post("/api/chat", json={"message": "search the web for dogs"}, headers=h))
    kinds = [e["event"] for e in events]
    assert "confirmation_required" not in kinds
    assert any(e["event"] == "tool_end" and e.get("success") for e in events)

    # revoke → back to confirmation flow
    r = auth_client.delete("/api/security/permissions/tools:web", headers=h)
    assert r.status_code == 200
    events = _events(auth_client.post("/api/chat", json={"message": "search the web for dogs"}, headers=h))
    assert any(e["event"] == "confirmation_required" for e in events)


def test_scope_denial_blocks_action(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/security/permissions",
                         json={"scope": "tasks:write", "allowed": False}, headers=h)
    assert r.status_code == 200
    events = _events(auth_client.post("/api/chat", json={"message": "create task Blocked task"}, headers=h))
    text = "".join(e.get("text", "") for e in events)
    assert "denied" in text.lower() or "blocked" in text.lower()
    # no task created
    assert all("Blocked task" != t["title"] for t in auth_client.get("/api/tasks").json()["tasks"])


def test_emergency_stop_blocks_everything(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/security/emergency-stop", json={"enabled": True}, headers=h)
    assert r.status_code == 200
    assert r.json()["active"] is True

    # low-risk write blocked
    events = _events(auth_client.post("/api/chat", json={"message": "create task Should fail"}, headers=h))
    text = "".join(e.get("text", "") for e in events)
    assert "emergency stop" in text.lower()
    # external action blocked without even a confirmation
    events = _events(auth_client.post("/api/chat", json={"message": "search the web for x"}, headers=h))
    text = "".join(e.get("text", "") for e in events)
    assert "emergency stop" in text.lower()

    # reads still work
    assert auth_client.get("/api/tasks").status_code == 200

    # release
    r = auth_client.post("/api/security/emergency-stop", json={"enabled": False}, headers=h)
    assert r.json()["active"] is False
    events = _events(auth_client.post("/api/chat", json={"message": "create task Now works"}, headers=h))
    assert any(t["title"] == "Now works" for t in auth_client.get("/api/tasks").json()["tasks"])


def test_emergency_stop_blocks_approved_confirmation(auth_client, monkeypatch):
    h = csrf_headers(auth_client)
    async def fake_search(q):
        return [{"title": "R", "url": "https://e.com", "snippet": "s"}]
    monkeypatch.setattr("mansik.tools.web_tools._duckduckgo_search", fake_search)
    events = _events(auth_client.post("/api/chat", json={"message": "search the web for x"}, headers=h))
    cid = [e for e in events if e["event"] == "confirmation_required"][0]["confirmation_id"]
    auth_client.post("/api/security/emergency-stop", json={"enabled": True}, headers=h)
    r = auth_client.post(f"/api/confirmations/{cid}/approve", headers=h)
    assert r.status_code == 422
    assert "Emergency stop" in r.json()["error"]["message"]


def test_permissions_listing(auth_client):
    r = auth_client.get("/api/security/permissions")
    assert r.status_code == 200
    perms = r.json()["permissions"]
    scopes = {p["scope"] for p in perms}
    assert {"tasks:write", "memory:write", "tools:web", "email:send"} <= scopes
    # nothing granted by default
    assert not any(p["granted"] for p in perms)
