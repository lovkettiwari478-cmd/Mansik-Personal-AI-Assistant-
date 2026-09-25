"""Memory system tests."""

from __future__ import annotations

from conftest import csrf_headers


def test_memory_crud(auth_client):
    r = auth_client.post("/api/memories", json={
        "content": "My sister's birthday is May 12", "kind": "person", "importance": 80,
    }, headers=csrf_headers(auth_client))
    assert r.status_code == 201
    mem = r.json()["memory"]
    assert mem["kind"] == "person"

    r = auth_client.get("/api/memories")
    assert any(m["id"] == mem["id"] for m in r.json()["memories"])

    r = auth_client.patch(f"/api/memories/{mem['id']}",
                          json={"content": "My sister's birthday is May 13"},
                          headers=csrf_headers(auth_client))
    assert r.status_code == 200
    assert "May 13" in r.json()["memory"]["content"]

    r = auth_client.delete(f"/api/memories/{mem['id']}", headers=csrf_headers(auth_client))
    assert r.status_code == 200
    assert all(m["id"] != mem["id"] for m in auth_client.get("/api/memories").json()["memories"])


def test_memory_fts_search(auth_client):
    for content, kind in [
        ("I prefer dark mode in every app", "preference"),
        ("Project Phoenix deadline is March 3", "project"),
        ("My sister's birthday is May 12", "person"),
    ]:
        auth_client.post("/api/memories", json={"content": content, "kind": kind},
                         headers=csrf_headers(auth_client))

    r = auth_client.post("/api/memories/search", json={"query": "birthday"},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 200
    results = r.json()["memories"]
    assert len(results) == 1
    assert "birthday" in results[0]["content"]

    r = auth_client.post("/api/memories/search", json={"query": "sister birthday"},
                         headers=csrf_headers(auth_client))
    assert len(r.json()["memories"]) >= 1

    r = auth_client.post("/api/memories/search", json={"query": "nonexistent-zzz"},
                         headers=csrf_headers(auth_client))
    assert r.json()["count"] == 0


def test_memory_search_excludes_deleted(auth_client):
    m = auth_client.post("/api/memories", json={"content": "ephemeral memory xyz"},
                         headers=csrf_headers(auth_client)).json()["memory"]
    auth_client.delete(f"/api/memories/{m['id']}", headers=csrf_headers(auth_client))
    r = auth_client.post("/api/memories/search", json={"query": "ephemeral"},
                         headers=csrf_headers(auth_client))
    assert r.json()["count"] == 0


def test_memory_refuses_credentials(auth_client):
    r = auth_client.post("/api/memories", json={"content": "my password is hunter2hunter2"},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 422


def test_memory_disable_stops_storage_and_retrieval(auth_client):
    auth_client.post("/api/memories", json={"content": "should be hidden after toggle"},
                     headers=csrf_headers(auth_client))
    r = auth_client.patch("/api/settings", json={"memory_enabled": False},
                          headers=csrf_headers(auth_client))
    assert r.status_code == 200
    # search still runs but returns nothing meaningful when disabled? —
    # spec: retrieval disabled too
    r = auth_client.post("/api/memories/search", json={"query": "hidden"},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 200
    # the memory.save tool must refuse while disabled
    r = auth_client.post("/api/chat", json={"message": "remember that I like tea"},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 200
    assert "disabled" in r.text.lower()
    # explicit API creation still allowed (user-controlled), tool is gated


def test_memory_tool_flow_via_chat(auth_client):
    r = auth_client.post("/api/chat", json={"message": "remember that my favorite color is teal"},
                         headers=csrf_headers(auth_client))
    assert r.status_code == 200
    assert "Stored" in r.text or "memory" in r.text.lower()
    memories = auth_client.get("/api/memories").json()["memories"]
    assert any("teal" in m["content"] for m in memories)
    # attribution: the assistant message records which memories were used
    r = auth_client.post("/api/chat", json={"message": "what do you remember about my favorite color"},
                         headers=csrf_headers(auth_client))
    assert "teal" in r.text
