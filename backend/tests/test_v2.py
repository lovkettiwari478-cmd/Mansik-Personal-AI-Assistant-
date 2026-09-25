"""v0.2.0 feature tests: personalization, home summary, verification
flags, tool labels/agents in SSE events."""

from __future__ import annotations

import json

from conftest import csrf_headers


def _events(response):
    events = []
    for chunk in response.text.strip().split("\n\n"):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events


def test_personalization_settings_roundtrip(auth_client):
    h = csrf_headers(auth_client)
    # defaults
    r = auth_client.get("/api/settings")
    assert r.json()["assistant_name"] == "MANISK"
    assert r.json()["response_style"] == "balanced"

    # update
    r = auth_client.patch("/api/settings", json={
        "assistant_name": "JARVIS", "response_style": "concise",
    }, headers=h)
    assert r.status_code == 200
    assert set(r.json()["changed"]) == {"assistant_name", "response_style"}

    r = auth_client.get("/api/settings")
    assert r.json()["assistant_name"] == "JARVIS"
    assert r.json()["response_style"] == "concise"

    # invalid style rejected
    r = auth_client.patch("/api/settings", json={"response_style": "verbose"},
                          headers=h)
    assert r.status_code == 422
    # name too long rejected
    r = auth_client.patch("/api/settings", json={"assistant_name": "x" * 50},
                          headers=h)
    assert r.status_code == 422


def test_home_summary_real_data(auth_client):
    h = csrf_headers(auth_client)
    # empty state first
    r = auth_client.get("/api/home/summary")
    body = r.json()
    assert body["tasks"]["open"] == 0
    assert body["tasks"]["due_today"] == 0
    assert body["memory_count"] == 0
    assert body["greeting"] in ("Good morning", "Good afternoon", "Good evening", "Good night")
    assert "local_time" in body and "timezone" in body

    # add real data → summary reflects it
    auth_client.post("/api/tasks", json={
        "title": "Today task", "due_at": "2026-09-25T12:00:00+00:00"}, headers=h)
    auth_client.post("/api/memories", json={"content": "home summary test memory"}, headers=h)
    auth_client.post("/api/calendar", json={
        "title": "Soon event", "starts_at": "2026-09-26T10:00:00+00:00",
        "ends_at": "2026-09-26T11:00:00+00:00"}, headers=h)

    r = auth_client.get("/api/home/summary")
    body = r.json()
    assert body["tasks"]["open"] == 1
    assert any(t["title"] == "Today task" for t in body["tasks"]["next"])
    assert body["memory_count"] == 1
    assert any(e["title"] == "Soon event" for e in body["events"])
    # recent activity contains REAL audit rows
    assert len(body["recent_activity"]) >= 3


def test_tool_events_carry_labels_and_agents(auth_client):
    h = csrf_headers(auth_client)
    events = _events(auth_client.post("/api/chat", json={
        "message": "create task Label test"}, headers=h))
    starts = [e for e in events if e["event"] == "tool_start"]
    ends = [e for e in events if e["event"] == "tool_end"]
    assert starts and ends
    assert starts[0]["label"] == "Creating task…"
    assert starts[0]["agent"] == "Task Agent"
    assert ends[0]["verified"] is True  # read-back verification flag


def test_create_tools_verify_readback(auth_client):
    h = csrf_headers(auth_client)
    # task
    events = _events(auth_client.post("/api/chat", json={
        "message": "create task Verify me"}, headers=h))
    end = [e for e in events if e["event"] == "tool_end"][0]
    assert end["output"]["verified"] is True
    # the task REALLY exists (independent of the tool's own claim)
    tasks = auth_client.get("/api/tasks").json()["tasks"]
    assert any(t["title"] == "Verify me" for t in tasks)

    # memory
    events = _events(auth_client.post("/api/chat", json={
        "message": "remember that verification works"}, headers=h))
    end = [e for e in events if e["event"] == "tool_end"][0]
    assert end["output"]["verified"] is True

    # calendar
    events = _events(auth_client.post("/api/chat", json={
        "message": "schedule Verified meeting tomorrow 10am"}, headers=h))
    end = [e for e in events if e["event"] == "tool_end"][0]
    assert end["output"]["verified"] is True


def test_user_message_survives_abort(auth_client):
    """Aborting mid-stream must not lose the user's message (commit-early)
    and must persist the partial assistant message (abort handling)."""
    import asyncio
    from sqlalchemy import select as sa_select
    from mansik.ai.orchestrator import Orchestrator
    from mansik.database import db_session
    from mansik.models import Conversation, Message, User, UserSettings, new_id

    db = db_session()
    user = db.get(User, auth_client.user["id"])
    ust = db.query(UserSettings).filter_by(user_id=user.id).one()
    convo = Conversation(id=new_id(), user_id=user.id, title="abort test")
    db.add(convo)
    db.commit()

    async def run():
        o = Orchestrator(db)
        agen = o.handle(
            user=user,
            user_settings=ust,
            conversation=convo,
            text="create task Abort probe",
        )
        # consume until the first tool_end, then simulate cancellation
        got_tool_end = False
        while True:
            ev = await agen.__anext__()
            if ev["event"] == "tool_end":
                got_tool_end = True
                break
        assert got_tool_end
        # BEFORE any further processing: user message already committed?
        db2 = db_session()
        found = db2.execute(
            sa_select(Message).where(Message.content == "create task Abort probe")
        ).scalars().all()
        db2.close()
        assert found, "user message must be committed before stream completes"
        # simulate client abort: CancelledError at the yield point
        try:
            await agen.athrow(asyncio.CancelledError)
        except (asyncio.CancelledError, StopAsyncIteration, GeneratorExit):
            pass

    asyncio.run(run())

    # user message AND partial assistant message persisted
    db3 = db_session()
    msgs = db3.execute(
        sa_select(Message).where(Message.conversation_id == convo.id)
        .order_by(Message.created_at)
    ).scalars().all()
    db3.close()
    roles = [m.role for m in msgs]
    assert "user" in roles
    assert "assistant" in roles, "partial assistant reply must persist on abort"
    aborted = [m for m in msgs if m.role == "assistant"][0]
    assert aborted.meta.get("aborted") is True
    assert aborted.meta.get("tools"), "tool execution record must persist on abort"
