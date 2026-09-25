"""Task + calendar API tests."""

from __future__ import annotations

from conftest import csrf_headers


def test_task_lifecycle(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/tasks", json={
        "title": "Buy groceries", "priority": "high",
        "due_at": "2027-06-01T17:00:00+00:00", "remind_minutes_before": 30,
    }, headers=h)
    assert r.status_code == 201
    task = r.json()["task"]
    assert task["status"] == "todo"
    assert task["priority"] == "high"

    r = auth_client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"}, headers=h)
    assert r.json()["task"]["status"] == "in_progress"

    r = auth_client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=h)
    assert r.json()["task"]["completed_at"] is not None

    r = auth_client.get("/api/tasks?status=done")
    assert any(t["id"] == task["id"] for t in r.json()["tasks"])

    r = auth_client.delete(f"/api/tasks/{task['id']}", headers=h)
    assert r.status_code == 200
    assert all(t["id"] != task["id"] for t in auth_client.get("/api/tasks").json()["tasks"])


def test_task_validation(auth_client):
    h = csrf_headers(auth_client)
    assert auth_client.post("/api/tasks", json={"title": ""}, headers=h).status_code == 422
    assert auth_client.post("/api/tasks", json={
        "title": "x", "priority": "insane"}, headers=h).status_code == 422
    assert auth_client.post("/api/tasks", json={
        "title": "x", "due_at": "not-a-date"}, headers=h).status_code == 422


def test_recurring_task_fields(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/tasks", json={
        "title": "Water plants", "recurrence": "weekly"}, headers=h)
    assert r.status_code == 201
    assert r.json()["task"]["recurrence"] == "weekly"


def test_event_lifecycle_and_validation(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/calendar", json={
        "title": "Team sync", "starts_at": "2027-03-01T09:00:00+00:00",
        "ends_at": "2027-03-01T10:00:00+00:00", "location": "Zoom",
        "reminder_minutes": 15,
    }, headers=h)
    assert r.status_code == 201
    event = r.json()["event"]

    # end before start → rejected
    r = auth_client.post("/api/calendar", json={
        "title": "Bad event", "starts_at": "2027-03-01T11:00:00+00:00",
        "ends_at": "2027-03-01T10:00:00+00:00"}, headers=h)
    assert r.status_code == 422

    r = auth_client.get("/api/calendar?days=365")
    assert any(e["id"] == event["id"] for e in r.json()["events"])

    r = auth_client.delete(f"/api/calendar/{event['id']}", headers=h)
    assert r.status_code == 200


def test_calendar_tool_conflict_detection(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/chat", json={
        "message": "schedule Dentist appointment tomorrow 3pm"}, headers=h)
    assert r.status_code == 200
    assert "Scheduled" in r.text

    r = auth_client.post("/api/chat", json={
        "message": "schedule Overlapping meeting tomorrow 3:15pm"}, headers=h)
    assert r.status_code == 200
    # second overlapping event should report the conflict
    assert "conflict" in r.text.lower() or "overlaps" in r.text.lower()


def test_upcoming_events_via_chat(auth_client):
    h = csrf_headers(auth_client)
    auth_client.post("/api/chat", json={"message": "schedule Standup tomorrow 9am"}, headers=h)
    r = auth_client.post("/api/chat", json={"message": "what's on my calendar"}, headers=h)
    assert r.status_code == 200
    assert "Standup" in r.text
