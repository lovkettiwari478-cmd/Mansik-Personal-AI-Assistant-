"""AI-mode orchestration end-to-end test using the local test-double
provider server (see test_providers.py — a TEST DOUBLE only, the shipped
app never fakes AI)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from conftest import csrf_headers

# Script the fake model's responses across the plan-execute-respond loop:
# 1st call → plan a tool call (JSON protocol)
# 2nd call → final reply (JSON protocol)
SCRIPTED_RESPONSES = [
    json.dumps({"tool_calls": [
        {"tool": "tasks.create", "params": {"title": "From AI plan", "priority": "high"},
         "reason": "user asked for a task"},
    ]}),
    json.dumps({"reply": "I created your task. Anything else?"}),
]


class FakeModel(BaseHTTPRequestHandler):
    call_count = 0

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        json.loads(self.rfile.read(length) or b"{}")
        idx = min(FakeModel.call_count, len(SCRIPTED_RESPONSES) - 1)
        FakeModel.call_count += 1
        if self.path.endswith("/chat/completions"):
            body = json.loads(self.rfile.read(0) or b"{}") if False else None
        # stream format with the scripted JSON
        payload = {
            "choices": [{"delta": {"content": SCRIPTED_RESPONSES[idx]}}]
        }
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


@pytest.fixture
def ai_client(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeModel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    FakeModel.call_count = 0

    from conftest import make_client
    c = make_client(
        tmp_path, monkeypatch,
        MANISK_AI_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
        MANISK_AI_MODEL="fake-model",
        MANISK_AI_API_KEY="test-key",
    )
    r = c.post("/api/auth/register", json={
        "email": "aimode@example.com", "password": "Str0ngPass!123", "display_name": "AI",
    })
    assert r.status_code == 201
    c.csrf = c.cookies.get("mansik_csrf")
    yield c
    server.shutdown()


def _events(response):
    events = []
    for chunk in response.text.strip().split("\n\n"):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events


def test_ai_mode_plan_execute_respond(ai_client):
    """Full loop: AI plans a tool call → executor runs it (through the
    firewall) → AI produces the final streamed reply."""
    h = csrf_headers(ai_client)
    r = ai_client.post("/api/chat", json={"message": "create a task called From AI plan"}, headers=h)
    assert r.status_code == 200
    events = _events(r)
    kinds = [e["event"] for e in events]

    assert events[0]["event"] == "meta"
    assert events[0]["mode"] == "ai"
    assert "tool_start" in kinds
    assert "tool_end" in kinds
    tool_end = [e for e in events if e["event"] == "tool_end"][0]
    assert tool_end["success"] is True
    assert tool_end["tool"] == "tasks.create"

    text = "".join(e.get("text", "") for e in events if e["event"] == "delta")
    assert "I created your task" in text

    # the task REALLY exists (no fabricated results)
    tasks = ai_client.get("/api/tasks").json()["tasks"]
    assert any(t["title"] == "From AI plan" and t["priority"] == "high" for t in tasks)

    # status endpoint reports AI configured (and no key leakage)
    status = ai_client.get("/api/status").json()
    assert status["ai_provider"]["configured"] is True
    assert "test-key" not in r.text


def test_ai_mode_status_reflected_in_chat_meta(ai_client):
    h = csrf_headers(ai_client)
    FakeModel.call_count = 99  # force the final reply script
    r = ai_client.post("/api/chat", json={"message": "hello"}, headers=h)
    events = _events(r)
    assert events[0]["mode"] == "ai"


def test_ai_mode_refuses_unknown_tool(ai_client):
    """The model proposing a nonexistent tool must not crash or fake it."""
    h = csrf_headers(ai_client)
    SCRIPTED_RESPONSES_LOCAL = json.dumps({"tool_calls": [
        {"tool": "nonexistent.tool", "params": {}, "reason": "hallucination"},
    ]})
    global SCRIPTED_RESPONSES
    original = list(SCRIPTED_RESPONSES)
    SCRIPTED_RESPONSES[0] = SCRIPTED_RESPONSES_LOCAL
    try:
        r = ai_client.post("/api/chat", json={"message": "do the thing"}, headers=h)
        assert r.status_code == 200
        events = _events(r)
        # unknown tool is reported honestly, not executed
        assert not any(e["event"] == "tool_end" and e.get("tool") == "nonexistent.tool"
                       and e.get("success") for e in events)
    finally:
        SCRIPTED_RESPONSES[:] = original
