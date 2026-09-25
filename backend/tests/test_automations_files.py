"""Automation + scheduler + files tests."""

from __future__ import annotations

import io

from conftest import csrf_headers


def test_automation_requires_grant_to_enable(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/automations", json={
        "name": "Daily digest", "trigger_type": "daily_at",
        "trigger_config": {"at_hhmm": "09:00"}, "action_tool": "notify.user",
        "action_params": {"title": "Good morning", "body": "Your day starts now."},
        "enabled": True,
    }, headers=h)
    assert r.status_code == 403  # no standing grant yet
    assert "notify" in r.json()["error"]["message"].lower() or "grant" in r.json()["error"]["message"].lower()

    # grant the scope, then enable
    auth_client.post("/api/security/permissions", json={"scope": "notify", "allowed": True}, headers=h)
    r = auth_client.post("/api/automations", json={
        "name": "Daily digest", "trigger_type": "daily_at",
        "trigger_config": {"at_hhmm": "09:00"}, "action_tool": "notify.user",
        "action_params": {"title": "Good morning", "body": "Your day starts now."},
        "enabled": True,
    }, headers=h)
    assert r.status_code == 201
    a = r.json()["automation"]
    assert a["enabled"] is True
    assert a["next_run_at"] is not None


def test_automation_validation(auth_client):
    h = csrf_headers(auth_client)
    # interval too short
    r = auth_client.post("/api/automations", json={
        "name": "fast", "trigger_type": "interval", "trigger_config": {"every_seconds": 10},
        "action_tool": "notify.user", "action_params": {"title": "x"}}, headers=h)
    assert r.status_code == 422
    # unknown tool
    r = auth_client.post("/api/automations", json={
        "name": "bad", "trigger_type": "interval", "trigger_config": {"every_seconds": 600},
        "action_tool": "no.such.tool", "action_params": {}}, headers=h)
    assert r.status_code == 422
    # tool without scope (time.now) cannot be automated
    r = auth_client.post("/api/automations", json={
        "name": "clock", "trigger_type": "interval", "trigger_config": {"every_seconds": 600},
        "action_tool": "time.now", "action_params": {}}, headers=h)
    assert r.status_code == 422
    # invalid params for the tool
    r = auth_client.post("/api/automations", json={
        "name": "bad params", "trigger_type": "interval", "trigger_config": {"every_seconds": 600},
        "action_tool": "notify.user", "action_params": {"wrong": "param"}}, headers=h)
    assert r.status_code == 422


def test_scheduler_executes_automation(auth_client):
    h = csrf_headers(auth_client)
    auth_client.post("/api/security/permissions", json={"scope": "notify", "allowed": True}, headers=h)
    r = auth_client.post("/api/automations", json={
        "name": "Every 5 min note", "trigger_type": "interval",
        "trigger_config": {"every_seconds": 300}, "action_tool": "notify.user",
        "action_params": {"title": "Ping", "body": "automated"},
        "enabled": True,
    }, headers=h)
    assert r.status_code == 201
    a = r.json()["automation"]

    # force the automation due now
    from mansik.database import db_session
    from mansik.models import Automation
    from datetime import datetime, timezone
    db = db_session()
    row = db.get(Automation, a["id"])
    row.next_run_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    db.close()

    from mansik.workers.scheduler import _tick
    _tick()

    runs = auth_client.get(f"/api/automations/{a['id']}/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "success"

    notifications = auth_client.get("/api/notifications").json()["notifications"]
    assert any("Ping" in n["title"] for n in notifications)

    # next run rescheduled in the future
    db = db_session()
    row = db.get(Automation, a["id"])
    assert row.next_run_at > datetime.now(timezone.utc)
    db.close()


def test_scheduler_skips_when_grant_revoked(auth_client):
    h = csrf_headers(auth_client)
    auth_client.post("/api/security/permissions", json={"scope": "notify", "allowed": True}, headers=h)
    r = auth_client.post("/api/automations", json={
        "name": "Revoked grant", "trigger_type": "interval",
        "trigger_config": {"every_seconds": 300}, "action_tool": "notify.user",
        "action_params": {"title": "Should skip"}, "enabled": True,
    }, headers=h)
    a = r.json()["automation"]

    # revoke
    auth_client.delete("/api/security/permissions/notify", headers=h)

    from mansik.database import db_session
    from mansik.models import Automation
    from datetime import datetime, timezone
    db = db_session()
    row = db.get(Automation, a["id"])
    row.next_run_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    db.close()

    from mansik.workers.scheduler import _tick
    _tick()

    runs = auth_client.get(f"/api/automations/{a['id']}/runs").json()["runs"]
    assert runs[0]["status"] == "skipped"
    assert "revoked" in runs[0]["error"] or "missing" in runs[0]["error"]


def test_scheduler_respects_emergency_stop(auth_client):
    h = csrf_headers(auth_client)
    auth_client.post("/api/security/permissions", json={"scope": "notify", "allowed": True}, headers=h)
    r = auth_client.post("/api/automations", json={
        "name": "Stopped", "trigger_type": "interval",
        "trigger_config": {"every_seconds": 300}, "action_tool": "notify.user",
        "action_params": {"title": "Nope"}, "enabled": True,
    }, headers=h)
    a = r.json()["automation"]
    auth_client.post("/api/security/emergency-stop", json={"enabled": True}, headers=h)

    from mansik.database import db_session
    from mansik.models import Automation
    from datetime import datetime, timezone
    db = db_session()
    row = db.get(Automation, a["id"])
    row.next_run_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    db.close()

    from mansik.workers.scheduler import _tick
    _tick()

    runs = auth_client.get(f"/api/automations/{a['id']}/runs").json()["runs"]
    assert runs[0]["status"] == "skipped"
    assert "emergency" in runs[0]["error"]


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def test_file_upload_download_delete(auth_client):
    h = csrf_headers(auth_client)
    content = b"MANISK file storage test\nline two"
    r = auth_client.post("/api/files", files={"file": ("notes.txt", io.BytesIO(content), "text/plain")},
                         headers=h)
    assert r.status_code == 201
    f = r.json()["file"]
    assert f["filename"] == "notes.txt"
    assert f["size_bytes"] == len(content)
    assert f["has_text"] is True

    r = auth_client.get(f"/api/files/{f['id']}/download")
    assert r.status_code == 200
    assert r.content == content

    listing = auth_client.get("/api/files").json()
    assert any(x["id"] == f["id"] for x in listing["files"])

    r = auth_client.delete(f"/api/files/{f['id']}", headers=h)
    assert r.status_code == 200
    assert auth_client.get(f"/api/files/{f['id']}/download").status_code == 404


def test_file_upload_rejects_bad_types(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/files", files={"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/x-msdownload")},
                         headers=h)
    assert r.status_code == 422
    r = auth_client.post("/api/files", files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
                         headers=h)
    assert r.status_code == 422


def test_file_upload_rejects_oversize(tmp_path, monkeypatch):
    from conftest import make_client
    c = make_client(tmp_path, monkeypatch, MANISK_MAX_UPLOAD_BYTES="100")
    c.post("/api/auth/register", json={"email": "f@f.co", "password": "Str0ngPass!123", "display_name": "F"})
    h = {"X-CSRF-Token": c.cookies.get("mansik_csrf")}
    r = c.post("/api/files", files={"file": ("big.txt", io.BytesIO(b"x" * 500), "text/plain")}, headers=h)
    assert r.status_code == 422


def test_file_isolation(auth_client, second_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/files", files={"file": ("secret.txt", io.BytesIO(b"private data"), "text/plain")},
                         headers=h)
    fid = r.json()["file"]["id"]
    assert second_client.get(f"/api/files/{fid}/download").status_code == 404
    assert second_client.delete(f"/api/files/{fid}", headers=csrf_headers(second_client)).status_code == 404
    assert all(x["id"] != fid for x in second_client.get("/api/files").json()["files"])


def test_file_binary_masquerade_rejected(auth_client):
    h = csrf_headers(auth_client)
    r = auth_client.post("/api/files", files={
        "file": ("fake.txt", io.BytesIO(b"\x00\x01\x02binary"), "text/plain")}, headers=h)
    assert r.status_code == 422
