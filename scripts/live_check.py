#!/usr/bin/env python3
"""Live smoke test against a RUNNING MANISK instance (default port 8000).

Verifies the v0.2 feature set over real HTTP: register/login, home summary
with real data, personalization, local-mode chat with tool execution +
labels, memory, tasks, security (permissions/emergency stop/audit),
settings, integrations honesty, and the SPA being served.
"""
from __future__ import annotations

import json
import secrets
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=30)
    r = c.get("/api/health")
    check("health 200", r.status_code == 200, str(r.status_code))
    check("version 0.2.0", r.json().get("version") == "0.2.0", r.text[:80])

    # SPA served
    r = c.get("/")
    check("SPA index served", r.status_code == 200 and "<div id=\"root\">" in r.text)
    r = c.get("/nonexistent-route")
    check("SPA fallback for client routes", r.status_code == 200 and "<div id=\"root\">" in r.text)

    # register
    # NOTE: the live server sets Secure cookies (correct for the HTTPS
    # preview). httpx will not replay Secure cookies over plain HTTP, so we
    # extract them from Set-Cookie and send them explicitly — exactly what
    # a browser does over HTTPS.
    email = f"live-{secrets.token_hex(4)}@mansik-test.dev"
    csrf = c.cookies.get("mansik_csrf", "")
    r = c.post("/api/auth/register", headers={"X-CSRF-Token": csrf},
               json={"email": email, "password": "LivePass!2026x", "display_name": "Live Test"})
    check("register", r.status_code in (200, 201), r.text[:120])

    cookies = {}
    for sc in r.headers.get_list("set-cookie"):
        pair = sc.split(";", 1)[0]
        k, _, v = pair.partition("=")
        cookies[k.strip()] = v.strip()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    H = {"X-CSRF-Token": cookies.get("mansik_csrf", ""), "Cookie": cookie_header}
    c.headers.update(H)  # send session on every subsequent request

    # status honest in local mode
    r = c.get("/api/status")
    s = r.json()
    check("status: no fake AI configured (local mode honest)",
          s.get("ai_provider", {}).get("configured") is False, r.text[:150])

    # home summary (v2)
    r = c.get("/api/home/summary")
    h = r.json()
    for k in ("greeting", "local_time", "tasks", "events", "memory_count", "unread_notifications"):
        check(f"home summary has .{k}", k in h, r.text[:200])
    check("home summary counts are real (tasks 0 for new user)", h.get("tasks", {}).get("open") == 0)

    # personalization
    r = c.patch("/api/settings", headers=H, json={"assistant_name": "JARVIS", "response_style": "concise"})
    check("personalization patch", r.status_code == 200, r.text[:120])
    r = c.get("/api/settings")
    check("personalization persisted", r.json().get("assistant_name") == "JARVIS")
    r = c.patch("/api/settings", headers=H, json={"response_style": "bogus"})
    check("invalid style rejected 422", r.status_code == 422, str(r.status_code))

    # local-mode chat with tool execution
    evs, text = [], ""
    with c.stream("POST", "/api/chat", headers=H,
                  json={"message": "remind me to buy milk tomorrow at 5pm high priority",
                        "conversation_id": None}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                evs.append(json.loads(line[6:]))
    kinds = [e["event"] for e in evs]
    check("chat SSE (local mode)", "done" in kinds, str(kinds))
    check("meta mode=local (honest)", any(e["event"] == "meta" and e.get("mode") == "local" for e in evs))
    ts = next((e for e in evs if e["event"] == "tool_start" and e.get("tool") == "tasks.create"), {})
    check("tool_start has label", "task" in (ts.get("label") or "").lower(), str(ts))
    check("tool_start has agent", "agent" in (ts.get("agent") or "").lower(), str(ts))
    te = next((e for e in evs if e["event"] == "tool_end" and e.get("tool") == "tasks.create"), {})
    check("tool_end verified (read-back)", te.get("verified") is True, str(te))
    r = c.get("/api/tasks")
    check("task really created", any("milk" in t["title"].lower() and "tomorrow" not in t["title"].lower() for t in r.json().get("tasks", [])), str([t["title"] for t in r.json().get("tasks", [])]))

    # memory via chat
    evs = []
    with c.stream("POST", "/api/chat", headers=H,
                  json={"message": "remember that my sister's birthday is May 12",
                        "conversation_id": None}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                evs.append(json.loads(line[6:]))
    te = next((e for e in evs if e["event"] == "tool_end" and e.get("tool") == "memory.save"), {})
    check("memory.save executed + verified", te.get("verified") is True, str(te))

    # tools + integrations honesty
    r = c.get("/api/tools")
    tools = r.json().get("tools", [])
    check("tools catalog", len(tools) >= 15, str(len(tools)))
    r = c.get("/api/integrations")
    ints = r.json().get("integrations", [])
    ai = next((i for i in ints if i["id"] == "ai-provider"), {})
    check("integrations honest: ai-provider not connected + env vars listed",
          ai.get("configured") is False and "MANISK_AI_BASE_URL" in ai.get("required_env", []), str(ai))

    # security: permissions + emergency stop + audit
    r = c.get("/api/security/permissions")
    check("permissions listed", r.status_code == 200 and len(r.json().get("permissions", [])) >= 5)
    r = c.get("/api/activity")
    check("audit trail has entries", len(r.json().get("activity", [])) >= 3)
    r = c.post("/api/security/emergency-stop", headers=H, json={"enabled": True})
    check("emergency stop on", r.status_code == 200 and r.json().get("active") is True)
    evs = []
    with c.stream("POST", "/api/chat", headers=H,
                  json={"message": "remind me to buy eggs", "conversation_id": None}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                evs.append(json.loads(line[6:]))
    text2 = " ".join(str(e) for e in evs)
    check("tool blocked during emergency stop",
          "Emergency" in text2 or "emergency" in text2.lower() or "blocked" in text2.lower(), text2[:200])
    r = c.post("/api/security/emergency-stop", headers=H, json={"enabled": False})
    check("emergency stop off", r.json().get("active") is False)

    # logout
    r = c.post("/api/auth/logout", headers=H)
    check("logout", r.status_code == 200)
    r = c.get("/api/home/summary")
    check("session revoked", r.status_code == 401, str(r.status_code))

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[:100]}]" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} live checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
