"""Chat flow tests (Local Mode) + conversation persistence."""

from __future__ import annotations

import json

from conftest import csrf_headers


def _events(response):
    events = []
    for chunk in response.text.strip().split("\n\n"):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events


def test_chat_stream_event_structure(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "what is 12 * (8+4)"}, headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _events(r)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "meta"
    assert "delta" in kinds
    assert kinds[-1] == "done"
    meta = events[0]
    assert meta["mode"] == "local"  # no provider configured in tests — honest
    done = events[-1]
    assert done["conversation_id"]
    assert done["execution_summary"]
    text = "".join(e.get("text", "") for e in events if e["event"] == "delta")
    assert "144" in text


def test_chat_persists_messages_and_context(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "remember that I work at Acme Corp"}, headers=h)
    cid = _events(r)[-1]["conversation_id"]

    r = auth_client.post("/api/chat", json={"conversation_id": cid, "message": "what do you remember about where I work"},
                         headers=h)
    events = _events(r)
    assert events[-1]["conversation_id"] == cid
    text = "".join(e.get("text", "") for e in events if e["event"] == "delta")
    assert "Acme" in text
    # memories attribution is surfaced
    assert any("memories_used" in e and e["memories_used"] for e in events if e["event"] == "meta")

    # message history persisted with metadata
    msgs = auth_client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert len(msgs) == 4
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["meta"].get("mode") == "local"
    assert msgs[-1]["meta"].get("tools")


def test_chat_local_mode_fallback_is_honest(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "what is the meaning of life?"}, headers=h)
    text = "".join(e.get("text", "") for e in _events(r) if e["event"] == "delta")
    assert "Local Mode" in text
    assert "AI provider" in text  # explains how to enable full AI


def test_chat_help(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "help"}, headers=h)
    text = "".join(e.get("text", "") for e in _events(r) if e["event"] == "delta")
    assert "Local Mode" in text and "create task" in text


def test_chat_task_flow_end_to_end(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={
        "message": "create task Submit tax documents due tomorrow 5pm with high priority"}, headers=h)
    text = "".join(e.get("text", "") for e in _events(r) if e["event"] == "delta")
    assert "Submit tax documents" in text

    tasks = auth_client.get("/api/tasks").json()["tasks"]
    task = [t for t in tasks if t["title"] == "Submit tax documents"][0]
    assert task["priority"] == "high"
    assert task["due_at"] is not None

    # complete it via chat
    r = auth_client.post("/api/chat", json={"message": "complete task Submit tax documents"}, headers=h)
    text = "".join(e.get("text", "") for e in _events(r) if e["event"] == "delta")
    assert "Completed" in text
    tasks = auth_client.get("/api/tasks").json()["tasks"]
    assert [t for t in tasks if t["title"] == "Submit tax documents"][0]["status"] == "done"


def test_chat_time_and_lists(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "what time is it"}, headers=h)
    kinds = [e["event"] for e in _events(r)]
    assert "tool_end" in kinds

    r = auth_client.post("/api/chat", json={"message": "show my tasks"}, headers=h)
    assert r.status_code == 200

    r = auth_client.post("/api/chat", json={"message": "list files"}, headers=h)
    assert r.status_code == 200


def test_chat_into_foreign_conversation_rejected(auth_client, second_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "hello there"}, headers=h)
    cid = _events(r)[-1]["conversation_id"]
    r = second_client.post("/api/chat", json={"conversation_id": cid, "message": "hi"},
                           headers=csrf_headers(second_client))
    assert r.status_code == 404


def test_conversation_listing_and_deletion(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={"message": "remember that test conversation exists"}, headers=h)
    cid = _events(r)[-1]["conversation_id"]
    convos = auth_client.get("/api/conversations").json()["conversations"]
    assert any(c["id"] == cid for c in convos)
    r = auth_client.delete(f"/api/conversations/{cid}", headers=h)
    assert r.status_code == 200
    convos = auth_client.get("/api/conversations").json()["conversations"]
    assert all(c["id"] != cid for c in convos)


def test_chat_rate_limit(tmp_path, monkeypatch):
    from conftest import make_client
    c = make_client(tmp_path, monkeypatch,
                    MANISK_RATE_LIMIT_ENABLED="true", MANISK_RATE_LIMIT_CHAT_PER_MINUTE="3")
    c.post("/api/auth/register", json={"email": "rl@example.com", "password": "Str0ngPass!123", "display_name": "R"})
    h = {"X-CSRF-Token": c.cookies.get("mansik_csrf")}
    codes = [c.post("/api/chat", json={"message": "what time is it"}, headers=h).status_code
             for _ in range(5)]
    assert 429 in codes
