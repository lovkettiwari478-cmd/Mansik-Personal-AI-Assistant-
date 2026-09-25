#!/usr/bin/env python3
"""MANISK end-to-end AI pipeline verification (development tool).

Spins up:
  1. a local OpenAI-compatible test double (scripts/ai_stub_server.py)
     — the sandbox cannot reach external AI providers, so the double
     speaks the same wire protocol as the user's real provider;
  2. the REAL MANISK backend (uvicorn subprocess, real HTTP + SSE on
     the wire, fresh SQLite runtime dir, scheduler off).

Then verifies, over real HTTP:
  A. /api/status reports the AI provider as configured with the stub model
  B. register + login + CSRF flow
  C. plain-text streaming chat (delta events, mode=ai)
  D. JSON {"reply"} streaming chat
  E. tool call round-trip: tasks.create executed through the permission
     firewall, tool_start/tool_end events carry label/agent/verified,
     task visible via REST afterwards (read-back)
  F. memory.save round-trip + REST read-back
  G. confirmation firewall: files.delete requires explicit approval;
     approve executes it; file gone afterwards
  H. conversation + message persistence incl. execution summaries
  I. emergency stop blocks tool execution mid-chat
  J. the AI API key never appears in any response body

Exit code 0 only if every check passes. Prints a PASS/FAIL table.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ai_stub_server import app as stub_app  # noqa: E402

STUB_PORT = 9753
APP_PORT = 8901
BASE = f"http://127.0.0.1:{APP_PORT}"
API_KEY_SENTINEL = "stub-key-e2e-DO-NOT-LEAK"

results: list[tuple[str, bool, str]] = []
all_bodies: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))


def start_stub() -> uvicorn.Server:
    config = uvicorn.Config(stub_app, host="127.0.0.1", port=STUB_PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def start_mansik(runtime: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "MANISK_DATABASE_URL": f"sqlite:///{runtime}/e2e.db",
        "MANISK_STORAGE_DIR": str(runtime / "files"),
        "MANISK_SESSION_SECRET": secrets.token_hex(32),
        "MANISK_AI_BASE_URL": f"http://127.0.0.1:{STUB_PORT}/v1",
        "MANISK_AI_MODEL": "mansik-stub",
        "MANISK_AI_API_KEY": API_KEY_SENTINEL,
        "MANISK_SCHEDULER_ENABLED": "false",
        "MANISK_ENVIRONMENT": "production",
        # plain HTTP locally: Secure cookies would never be sent back
        "MANISK_COOKIE_SECURE": "false",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mansik.main:app",
         "--host", "127.0.0.1", "--port", str(APP_PORT), "--log-level", "warning"],
        cwd=str(ROOT / "backend"), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return proc


def wait_health(client: httpx.Client, proc: subprocess.Popen, timeout=40) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            print("MANISK died during startup:\n", out[-3000:])
            return False
        try:
            r = client.get(f"{BASE}/api/health", timeout=2)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.4)
    return False


def csrf(client: httpx.Client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("mansik_csrf", "")}


def stream_chat(client: httpx.Client, message: str, conversation_id: str | None = None):
    """POST /api/chat and collect SSE events."""
    events = []
    text_acc = ""
    with client.stream(
        "POST", f"{BASE}/api/chat",
        headers=csrf(client),
        json={"message": message, "conversation_id": conversation_id},
        timeout=60,
    ) as r:
        all_bodies.append(f"status={r.status_code}")
        if r.status_code != 200:
            body = r.read().decode()
            all_bodies.append(body)
            return r.status_code, events, text_acc
        buffer = ""
        for line in r.iter_lines():
            buffer += line + "\n"
            if line == "":
                chunk = buffer.strip()
                buffer = ""
                if chunk.startswith("data: "):
                    try:
                        ev = json.loads(chunk[6:])
                        events.append(ev)
                        if ev.get("event") == "delta":
                            text_acc += ev.get("text", "")
                        all_bodies.append(json.dumps(ev))
                    except json.JSONDecodeError:
                        pass
    return 200, events, text_acc


def main() -> int:
    runtime = Path(tempfile.mkdtemp(prefix="mansik_e2e_"))
    (runtime / "files").mkdir()
    print("== MANISK E2E AI pipeline verification ==")
    print(f"runtime dir: {runtime}")

    stub = start_stub()
    proc = start_mansik(runtime)
    try:
        with httpx.Client(timeout=15) as client:
            if not wait_health(client, proc):
                check("server starts", False)
                return finish(proc)
            check("server starts (real uvicorn, /api/health 200)", True)

            # (status checks moved after auth — /api/status requires a session)

            # --- B. auth ---
            email = f"e2e-{secrets.token_hex(4)}@mansik-test.dev"
            r = client.post(f"{BASE}/api/auth/register", headers=csrf(client),
                            json={"email": email, "password": "E2EPass!2026x", "display_name": "E2E"})
            all_bodies.append(r.text)
            check("B1 register 200/201", r.status_code in (200, 201), f"got {r.status_code}: {r.text[:200]}")
            check("B2 session cookie set", "mansik_session" in client.cookies or
                  any(c.name == "mansik_session" for c in client.cookies.jar))
            check("B3 csrf cookie set", "mansik_csrf" in client.cookies)

            # --- A. provider configured via env only (authed) ---
            r = client.get(f"{BASE}/api/status")
            all_bodies.append(r.text)
            s = r.json()
            check("A1 /api/status ai_provider.configured == true",
                  s.get("ai_provider", {}).get("configured") is True)
            check("A2 model name reported (mansik-stub)",
                  s.get("ai_provider", {}).get("model") == "mansik-stub")
            check("A3 api key not in /api/status", API_KEY_SENTINEL not in r.text)

            # --- C. plain-text streaming ---
            code, events, text = stream_chat(client, "hello there")
            kinds = [e["event"] for e in events]
            check("C1 HTTP 200 SSE", code == 200)
            check("C2 meta event mode=ai", any(e["event"] == "meta" and e.get("mode") == "ai" for e in events))
            check("C3 delta events streamed", kinds.count("delta") >= 1)
            check("C4 full reply assembled", "streamed plain-text reply" in text, text[:120])
            check("C5 done event", "done" in kinds)
            conv1 = next((e.get("conversation_id") for e in events if e["event"] == "done"), None)

            # --- D. JSON {"reply"} streaming ---
            code, events, text = stream_chat(client, "please reply using the json format")
            check("D1 JSON reply path works", "streamed JSON object" in text, text[:120])

            # --- E. tool call: tasks.create ---
            code, events, text = stream_chat(client, "remind me to buy milk tomorrow at 5pm, high priority")
            starts = [e for e in events if e["event"] == "tool_start"]
            ends = [e for e in events if e["event"] == "tool_end"]
            check("E1 tool_start emitted", any(e["tool"] == "tasks.create" for e in starts),
                  json.dumps(starts[:1]))
            ts = next((e for e in starts if e["tool"] == "tasks.create"), {})
            check("E2 tool_start carries friendly label", "task" in (ts.get("label") or "").lower(), str(ts))
            check("E3 tool_start carries agent", "agent" in (ts.get("agent") or "").lower(), str(ts))
            te = next((e for e in ends if e["tool"] == "tasks.create"), {})
            check("E4 tool_end success", te.get("success") is True, str(te))
            check("E5 tool_end verified (db read-back)", te.get("verified") is True, str(te))
            check("E6 final reply reflects verification", "verify" in text.lower(), text[:160])
            r = client.get(f"{BASE}/api/tasks")
            all_bodies.append(r.text)
            titles = [t["title"] for t in r.json().get("tasks", [])]
            check("E7 task persisted (REST read-back)", "Buy milk" in titles, str(titles))

            # --- F. memory.save ---
            code, events, text = stream_chat(
                client, "please remember that my sister's birthday is May 12")
            te = next((e for e in events if e["event"] == "tool_end" and e["tool"] == "memory.save"), {})
            check("F1 memory.save executed + verified",
                  te.get("success") is True and te.get("verified") is True, str(te))
            r = client.get(f"{BASE}/api/memories")
            all_bodies.append(r.text)
            contents = [m["content"] for m in r.json().get("memories", [])]
            check("F2 memory persisted (REST read-back)",
                  any("sister" in c.lower() for c in contents), str(contents)[:160])

            # --- G. confirmation firewall: files.delete ---
            r = client.post(f"{BASE}/api/files", headers=csrf(client),
                            files={"file": ("notes.txt", b"hello e2e", "text/plain")})
            all_bodies.append(r.text)
            file_id = r.json().get("file", {}).get("id", "")
            check("G1 file uploaded", bool(file_id), r.text[:200])
            code, events, text = stream_chat(client, f"delete my file notes.txt id={file_id}")
            conf = next((e for e in events if e["event"] == "confirmation_required"), None)
            check("G2 confirmation_required emitted (no execution without approval)",
                  conf is not None and conf.get("tool") == "files.delete", json.dumps(events)[:300])
            check("G3 file still present before approval", any(
                f["id"] == file_id for f in client.get(f"{BASE}/api/files").json().get("files", [])))
            if conf:
                r = client.post(f"{BASE}/api/confirmations/{conf['confirmation_id']}/approve",
                                headers=csrf(client))
                all_bodies.append(r.text)
                check("G4 approve executes + reports result", r.status_code == 200, r.text[:200])
                files_after = client.get(f"{BASE}/api/files").json().get("files", [])
                check("G5 file deleted after approval",
                      not any(f["id"] == file_id for f in files_after), str(files_after))

            # --- H. persistence ---
            r = client.get(f"{BASE}/api/conversations")
            all_bodies.append(r.text)
            convs = r.json().get("conversations", [])
            check("H1 conversations listed", len(convs) >= 2, str(len(convs)))
            if convs:
                cid = convs[0]["id"]
                r = client.get(f"{BASE}/api/conversations/{cid}/messages")
                all_bodies.append(r.text)
                msgs = r.json().get("messages", [])
                asst = [m for m in msgs if m["role"] == "assistant"]
                with_tools = [m for m in asst if (m.get("meta") or {}).get("tools")]
                check("H2 messages persisted with execution summaries", len(with_tools) >= 1,
                      f"{len(msgs)} msgs, {len(asst)} assistant")

            # --- I. emergency stop ---
            r = client.post(f"{BASE}/api/security/emergency-stop", headers=csrf(client),
                            json={"enabled": True})
            all_bodies.append(r.text)
            check("I1 emergency stop enabled", r.status_code == 200)
            code, events, text = stream_chat(client, "remind me to buy milk again please")
            te = [e for e in events if e["event"] == "tool_end"]
            starts2 = [e for e in events if e["event"] == "tool_start"]
            check("I2 tool execution blocked while stopped",
                  (not starts2) or any(not e.get("success") for e in te),
                  json.dumps([e for e in events if e["event"] in ("tool_start", "tool_end")])[:200])
            r = client.post(f"{BASE}/api/security/emergency-stop", headers=csrf(client),
                            json={"enabled": False})
            check("I3 emergency stop released", r.status_code == 200)

            # --- J. secret leakage scan ---
            leaked = [b for b in all_bodies if API_KEY_SENTINEL in b]
            check("J1 AI API key never appears in any response body", not leaked,
                  f"leaked in {len(leaked)} bodies")

        return finish(proc)
    finally:
        pass


def finish(proc: subprocess.Popen) -> int:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("\n== RESULTS ==")
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail[:120]}]" if detail and not ok else ""))
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
