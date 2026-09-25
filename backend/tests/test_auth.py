"""Authentication tests — success and failure paths."""

from __future__ import annotations

from conftest import csrf_headers


def test_register_login_me_logout(client):
    r = client.post("/api/auth/register", json={
        "email": "alice@example.com", "password": "Str0ngPass!123", "display_name": "Alice",
    })
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "alice@example.com"
    assert "password" not in str(r.json())
    assert "mansik_session" in client.cookies

    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "alice@example.com"

    r = client.post("/api/auth/logout", headers=csrf_headers(client))
    assert r.status_code == 200
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_register_duplicate_email(client):
    body = {"email": "dup@example.com", "password": "Str0ngPass!123", "display_name": "A"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 409


def test_register_weak_passwords(client):
    # single character-class or too short → rejected (403 policy or 422 schema)
    for pw in ("short", "alllowercase", "1234567890", "NOLOWERCASE"):
        r = client.post("/api/auth/register", json={
            "email": "weak@example.com", "password": pw, "display_name": "W",
        })
        assert r.status_code in (403, 422), pw
    # two classes + length → accepted
    r = client.post("/api/auth/register", json={
        "email": "okuser@example.com", "password": "lowercase123", "display_name": "W",
    })
    assert r.status_code == 201


def test_login_failures_indistinguishable(client):
    client.post("/api/auth/register", json={
        "email": "real@example.com", "password": "Str0ngPass!123", "display_name": "R",
    })
    client.post("/api/auth/logout", headers=csrf_headers(client))

    wrong_pw = client.post("/api/auth/login", json={"email": "real@example.com", "password": "WrongPassword1"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "WhateverPass1"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_login_success_after_logout(client):
    client.post("/api/auth/register", json={
        "email": "again@example.com", "password": "Str0ngPass!123", "display_name": "A",
    })
    client.post("/api/auth/logout", headers=csrf_headers(client))
    r = client.post("/api/auth/login", json={"email": "again@example.com", "password": "Str0ngPass!123"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_change_password_revokes_other_sessions(client):
    client.post("/api/auth/register", json={
        "email": "multi@example.com", "password": "Str0ngPass!123", "display_name": "M",
    })
    # second session on a separate client (same DB)

    # open a second session (overwrites the cookie, simulating another device)
    login2 = client.post("/api/auth/login", json={"email": "multi@example.com", "password": "Str0ngPass!123"})
    assert login2.status_code == 200

    r = client.post("/api/auth/change-password",
                    headers=csrf_headers(client),
                    json={"current_password": "Str0ngPass!123", "new_password": "BrandNewPass!789"})
    assert r.status_code == 200
    assert r.json()["sessions_revoked"] >= 1

    r = client.post("/api/auth/login", json={"email": "multi@example.com", "password": "BrandNewPass!789"})
    assert r.status_code == 200


def test_change_password_wrong_current(auth_client):
    r = auth_client.post("/api/auth/change-password",
                         headers=csrf_headers(auth_client),
                         json={"current_password": "NopeWrong!11", "new_password": "BrandNewPass!789"})
    assert r.status_code == 401


def test_session_listing_and_revocation(auth_client):
    r = auth_client.get("/api/auth/sessions")
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert len(sessions) >= 1
    current = [s for s in sessions if s["current"]][0]
    r = auth_client.delete(f"/api/auth/sessions/{current['id']}", headers=csrf_headers(auth_client))
    assert r.status_code == 200
    assert auth_client.get("/api/auth/me").status_code == 401


def test_logout_all(auth_client):
    r = auth_client.post("/api/auth/logout-all", headers=csrf_headers(auth_client))
    assert r.status_code == 200
    assert auth_client.get("/api/auth/me").status_code == 401
