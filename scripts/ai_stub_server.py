"""Local OpenAI-compatible test double for MANISK E2E verification.

DEVELOPMENT/VERIFICATION TOOL ONLY — never used in production.
Implements POST /v1/chat/completions (streaming + non-streaming) with
deterministic "model" behavior so the real MANISK provider client,
orchestrator protocol ({"reply"} / {"tool_calls"}), tool execution and
confirmation flows can be verified end-to-end without external network
access. The sandbox blocks external AI providers, so this double stands
in for the user's real provider (same wire protocol).

Run standalone:
    python scripts/ai_stub_server.py [port]

Behavior (deterministic, driven by the last user message):
    - message contains "TOOL OUTPUT" -> stream {"reply": ...} JSON that
      reflects the verified tool result embedded in the conversation
    - message contains "APPROVED ACTION" (confirmation continuation,
      non-streaming) -> concise truthful outcome text
    - "hello" -> plain-text streaming reply (non-JSON path)
    - "json" -> {"reply": ...} streamed as JSON (JSON path)
    - "milk" -> {"tool_calls": [tasks.create ...]}
    - "remember" + "sister" -> {"tool_calls": [memory.save ...]}
    - "delete" + "file" -> {"tool_calls": [files.delete ...]} (id=... parsed)
    - default -> {"reply": "OK."}
"""

from __future__ import annotations

import json
import re
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="MANISK AI test double")


def _last_user_message(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def _decide(messages: list[dict]) -> str:
    """Return the raw assistant content for this completion."""
    text = _last_user_message(messages)

    if "TOOL OUTPUT" in text:
        # Tool results round-trip: reply honestly based on verified output.
        compact = text.replace(" ", "")
        if '"success":true' in compact:
            verified = '"verified":true' in compact
            what = "task"
            if "memory.save" in text:
                what = "memory"
            elif "calendar.create_event" in text:
                what = "event"
            elif "files.delete" in text:
                what = "file deletion"
            if verified:
                return json.dumps({
                    "reply": f"Done — I read back the new {what} record from the database to "
                             f"verify it, and everything checks out. It's saved and visible in "
                             f"your {what} list."
                })
        if "files.delete" in text:
            return json.dumps({"reply": "The file was deleted after your approval. I verified "
                                        "it is no longer in your storage."})
        return json.dumps({"reply": "The tool ran; check the summary above."})

    if "APPROVED ACTION" in text:
        return "The approved action completed successfully — I verified the result before reporting it."

    low = text.lower()
    if "milk" in low:
        return json.dumps({"tool_calls": [{
            "tool": "tasks.create",
            "params": {
                "title": "Buy milk",
                "notes": "From the chat E2E test",
                "priority": "high",
                "due": "tomorrow 5pm",
            },
            "reason": "User asked to be reminded to buy milk tomorrow at 5pm with high priority.",
        }]})

    if "remember" in low and "sister" in low:
        return json.dumps({"tool_calls": [{
            "tool": "memory.save",
            "params": {"content": "User's sister's birthday is May 12", "kind": "person"},
            "reason": "User asked me to remember a personal fact.",
        }]})

    if "delete" in low and "file" in low:
        m = re.search(r"id[=:\s]+([a-z0-9]{8,64})", low)
        params = {"file_id": m.group(1)} if m else {"file_id": "unknown"}
        return json.dumps({"tool_calls": [{
            "tool": "files.delete",
            "params": params,
            "reason": "User explicitly asked to delete their uploaded file.",
        }]})

    if "hello" in low or "hi " in low or low.strip() == "hi":
        return ("Hello! This is a streamed plain-text reply from the local test double. "
                "The full pipeline — auth, context, provider streaming, persistence — is working.")

    if "json" in low:
        return json.dumps({"reply": "This reply arrived as a streamed JSON object and was "
                                    "unpacked by the orchestrator."})

    return json.dumps({"reply": "OK."})


def _chunks(content: str):
    """Split content into small chunks like a real streaming model."""
    out = []
    step = 24
    for i in range(0, len(content), step):
        out.append(content[i:i + step])
    if not out:
        out = [""]
    return out


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "mansik-stub", "object": "model"}]}


@app.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": {"message": "missing api key"}}, status_code=401)
    messages = body.get("messages", [])
    content = _decide(messages)

    if not body.get("stream"):
        return {
            "id": "stub-1", "object": "chat.completion", "model": body.get("model", "mansik-stub"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
        }

    async def gen():
        for chunk in _chunks(content):
            yield "data: " + json.dumps({
                "id": "stub-1", "object": "chat.completion.chunk",
                "model": body.get("model", "mansik-stub"),
                "choices": [{"index": 0, "finish_reason": None,
                             "delta": {"role": "assistant", "content": chunk}}],
            }) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9753
    print(f"MANISK AI test double on http://127.0.0.1:{port}/v1")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
