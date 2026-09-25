#!/usr/bin/env python3
"""MANISK deployment verification — run against ANY live instance.

Usage:
    python scripts/live_check.py https://your-app.onrender.com
    backend/.venv/bin/python scripts/live_check.py        # local dev server

Only dependency: httpx  (pip install httpx)

Mode-aware:
  - Real AI mode (MANISK_AI_* configured server-side): verifies streaming
    chat through the actual provider, tool execution requested of the
    model, verified DB read-backs, and the permission firewall.
  - Local Mode (no provider): verifies the honest deterministic router.

Cold-start tolerant: retries /api/health for up to 3 minutes (free-tier
services can take ~1 minute to wake up).
"""
from __future__ import annotations

import json
import secrets
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))


def info(msg: str) -> None:
    print(f"  ℹ️  {msg}")


def wait_health(c: httpx.Client, timeout_s: int = 180):
    """Cold-start tolerant health wait. Returns (ok, detail)."""
    deadline = time.time() + timeout_s
    last = "never reached"
    announced = False
    while time.time() < deadline:
        try:
            r = c.get("/api/health", timeout=15)
            if r.status_code == 200:
                return True, r.text
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last = type(e).__name__
        if not announced:
            print("  (waiting for the instance to wake up…)")
            announced = True
        time.sleep(4)
    return False, last


def cookie_headers(r: httpx.Response) -> dict:
    """Extract session + csrf cookies from Set-Cookie and return explicit
    Cookie/X-CSRF-Token headers. (Needed when a client that respects the
    Secure flag talks to a plain-HTTP target; over HTTPS httpx replays
    cookies on its own — this works for both.)"""
    cookies = {}
    for sc in r.headers.get_list("set-cookie"):
        k, _, v = sc.split(";", 1)[0].partition("=")
        cookies[k.strip()] = v.strip()
    return {
        "X-CSRF-Token": cookies.get("mansik_csrf", ""),
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }


def chat(c: httpx.Client, message: str):
    """POST /api/chat, return the list of SSE events."""
    evs: list[dict] = []
    with c.stream("POST", "/api/chat",
                  json={"message": message, "conversation_id": None},
                  timeout=120) as r:
        if r.status_code != 200:
            return [{"event": "http_error", "status": r.status_code,
                     "body": r.read().decode()[:200]}]
        for line in r.iter_lines():
            if line.startswith("data: "):
                try:
                    evs.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return evs


def tool_end(evs: list[dict], tool: str) -> dict:
    return next((e for e in evs if e.get("event") == "tool_end" and e.get("tool") == tool), {})


def main() -> int:
    print(f"== MANISK deployment verification ==\n target: {BASE}")
    c = httpx.Client(base_url=BASE, timeout=30)

    ok, detail = wait_health(c)
    check("instance reachable + healthy (cold-start tolerant)", ok, detail)
    if not ok:
        return finish()
    try:
        version = json.loads(detail).get("version")
    except Exception:
        version = None
    check("backend version reported", bool(version), str(version))
    info(f"running MANISK v{version}")

    # SPA
    r = c.get("/")
    check("SPA index served", r.status_code == 200 and '<div id="root">' in r.text)
    r = c.get("/nonexistent-client-route")
    check("SPA fallback for client routes", r.status_code == 200 and '<div id="root">' in r.text)

    # register
    email = f"verify-{secrets.token_hex(4)}@mansik-test.dev"
    r = c.post("/api/auth/register",
               headers={"X-CSRF-Token": c.cookies.get("mansik_csrf", "")},
               json={"email": email, "password": "VerifyPass!2026",
                     "display_name": "Deployment Check"})
    check("register (10+ char password)", r.status_code in (200, 201), r.text[:120])
    H = cookie_headers(r)
    check("session + csrf cookies set", "mansik_session" in H["Cookie"] and bool(H["X-CSRF-Token"]))
    c.headers.update(H)

    # mode detection
    r = c.get("/api/status")
    s = r.json()
    ai = s.get("ai_provider", {}) or {}
    ai_mode = bool(ai.get("configured"))
    if ai_mode:
        check("AI provider configured (real AI mode)", True, f"model = {ai.get('model')}")
    else:
        check("no AI provider configured — honest Local Mode", True)
        info("set MANISK_AI_* env vars on the server to enable real AI")

    # home summary
    r = c.get("/api/home/summary")
    h = r.json()
    for k in ("greeting", "local_time", "tasks", "events", "memory_count",
              "unread_notifications"):
        check(f"home summary has .{k}", k in h, r.text[:200])
    check("home summary counts are real (new user: 0 open tasks)",
          h.get("tasks", {}).get("open") == 0)

    # personalization
    r = c.patch("/api/settings", json={"assistant_name": "JARVIS", "response_style": "concise"})
    check("personalization patch", r.status_code == 200, r.text[:120])
    r = c.get("/api/settings")
    check("personalization persisted",
          r.json().get("assistant_name") == "JARVIS" and r.json().get("response_style") == "concise")
    r = c.patch("/api/settings", json={"response_style": "bogus"})
    check("invalid style rejected (422)", r.status_code == 422, str(r.status_code))

    # ---- chat + tools --------------------------------------------------
    evs = chat(c, "hello")
    kinds = [e.get("event") for e in evs]
    check("chat SSE streaming completes (done event)", "done" in kinds, str(kinds[:6]))
    reply = "".join(e.get("text", "") for e in evs if e.get("event") == "delta")
    check("chat reply is non-empty", len(reply.strip()) > 0, reply[:120])
    meta = next((e for e in evs if e.get("event") == "meta"), {})
    check("mode reported honestly (meta event)",
          meta.get("mode") == ("ai" if ai_mode else "local"), str(meta))

    # tool execution through chat (deterministic router in Local Mode;
    # explicit instruction in AI mode — the system prompt forbids claiming
    # success without a verified TOOL OUTPUT, so a compliant model MUST
    # call the tool)
    if ai_mode:
        evs = chat(c, "Create a task titled 'live verification probe' with priority "
                      "'low' using the tasks.create tool now, then confirm in one sentence.")
    else:
        evs = chat(c, "remind me to buy milk tomorrow at 5pm high priority")
    te = tool_end(evs, "tasks.create")
    check("task created through chat (tasks.create executed)",
          te.get("success") is True, json.dumps(evs)[:220])
    check("tool result verified by DB read-back", te.get("verified") is True, str(te))
    ts = next((e for e in evs if e.get("event") == "tool_start"
               and e.get("tool") == "tasks.create"), {})
    check("tool events carry friendly label + agent",
          "task" in (ts.get("label") or "").lower() and "agent" in (ts.get("agent") or "").lower(),
          str(ts))
    r = c.get("/api/tasks")
    titles = [t["title"] for t in r.json().get("tasks", [])]
    check("task persisted (REST read-back)",
          any("probe" in t.lower() or "milk" in t.lower() for t in titles), str(titles))

    # memory through chat
    evs = chat(c, "Please remember that my sister's birthday is May 12 — use the "
                  "memory.save tool now.")
    te = tool_end(evs, "memory.save")
    check("memory saved through chat (verified read-back)",
          te.get("success") is True and te.get("verified") is True, str(te))
    r = c.get("/api/memories")
    check("memory persisted (REST read-back)",
          any("sister" in m.get("content", "").lower()
              for m in r.json().get("memories", [])))

    # catalog + integrations honesty
    r = c.get("/api/tools")
    tools = r.json().get("tools", [])
    check("tool catalog served (16 tools)", len(tools) >= 15, str(len(tools)))
    r = c.get("/api/integrations")
    ints = r.json().get("integrations", [])
    ai_int = next((i for i in ints if i.get("id") == "ai-provider"), {})
    check("integrations honesty (configured flag matches reality)",
          bool(ai_int.get("configured")) == ai_mode, str(ai_int))
    check("integrations list required env vars",
          "MANISK_AI_BASE_URL" in ai_int.get("required_env", []))

    # security surface
    r = c.get("/api/security/permissions")
    check("permission scopes listed", len(r.json().get("permissions", [])) >= 5)
    r = c.get("/api/activity")
    check("audit trail records actions", len(r.json().get("activity", [])) >= 3)

    # emergency stop
    r = c.post("/api/security/emergency-stop", json={"enabled": True})
    check("emergency stop activates", r.status_code == 200 and r.json().get("active") is True)
    evs = chat(c, "Create a task titled 'estop probe' using the tasks.create tool right now.")
    succeeded = [e for e in evs if e.get("event") == "tool_end" and e.get("success")]
    check("NO tool executed while emergency stop active", not succeeded,
          json.dumps(evs)[:220])
    r = c.post("/api/security/emergency-stop", json={"enabled": False})
    check("emergency stop releases", r.json().get("active") is False)

    # auth teardown
    r = c.post("/api/auth/logout")
    check("logout", r.status_code == 200)
    r = c.get("/api/home/summary")
    check("session revoked server-side (401 after logout)", r.status_code == 401, str(r.status_code))

    return finish()


def finish() -> int:
    print("\n== RESULTS ==")
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[:110]}]" if detail and not ok else ""))
    total = len(results)
    verdict = "  ✅ DEPLOYMENT VERIFIED" if passed == total and total else ""
    print(f"\n{passed}/{total} checks passed{verdict}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
