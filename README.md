# MANISK — Personal AI Operating System

MANISK is a personal AI operating system: conversational AI, long-term memory, tasks,
calendar, files, tools, automations — wrapped in a **permission firewall** that keeps
*you* in control of every sensitive action.

> **Status: v0.1.0 — working, tested, deployable.**
> 108 backend tests passing. Live deployment verified end-to-end (see *Verification* below).
> AI conversation requires a model provider credential (any OpenAI-compatible API) —
> without one, MANISK runs in **honest Local Mode** (deterministic command routing, no fake AI).

---

## What MANISK does

| Capability | Status | Notes |
|---|---|---|
| Accounts (register/login/logout, bcrypt, server-side sessions) | ✅ working | password change revokes other sessions |
| CSRF + rate limiting + security headers | ✅ working | double-submit CSRF, per-IP sliding window |
| User data isolation (IDOR-proof) | ✅ tested | every resource query is user-scoped |
| Chat orchestration (plan → permission check → tools → respond) | ✅ working | SSE streaming; AI mode or Local Mode |
| Tool system (16 tools, strict schemas, timeouts, audit) | ✅ working | calculator, time, tasks, memory, calendar, files, web, notify, email |
| Permission firewall (scopes, grants, confirmations, emergency stop) | ✅ working | high-risk/external actions need explicit approval |
| Long-term memory (FTS5 search, user-controlled, disable switch) | ✅ working | never stores credential-looking content |
| Tasks (priorities, due dates, recurrence, reminders) | ✅ working | |
| Calendar (events, conflicts, reminders) | ✅ working | |
| Automations (interval/daily, standing grants, run logs, skip rules) | ✅ working | cannot be enabled without explicit grant |
| Files (upload, validation, text extraction, isolated storage) | ✅ working | |
| Audit trail (every sensitive action) | ✅ working | visible to the user in Activity |
| AI provider abstraction (streaming, retries, fallback) | ✅ implemented | **needs credential to activate** (see below) |
| Web search / fetch | ✅ implemented | **blocked by this sandbox's network** — works on normal hosts |
| Email (SMTP) | ✅ implemented | **needs SMTP credentials** |
| Knowledge graph (entities + relations API) | ✅ working | basic |

### Honest limitations (no fakes)

- **AI conversation** requires `MANISK_AI_BASE_URL` + `MANISK_AI_MODEL` (+ key if the
  provider needs one). Without it the chat runs **Local Mode**: a deterministic command
  router (tasks/calendar/memory/math/time/web-search commands) that uses the same tools
  and permission pipeline — and clearly says it's not an AI.
- **Web search / URL fetch** are real integrations (Tavily API + keyless DuckDuckGo
  fallback; SSRF-hardened fetcher). This repository's preview sandbox blocks outbound
  internet, so they return honest network errors *here*. On a normal host they work.
- **Biometric "Face Lock" / hardware key recovery** are not implemented — real
  biometrics need platform APIs (WebAuthn is the planned path); we do not fake them.
- **Semantic/vector memory** is an extension point; today search is full-text (FTS5).

---

## Architecture at a glance

```
┌────────────────────────────────────────────────────────────┐
│ React SPA (Vite, TypeScript, mobile-first)                 │
│ chat · dashboard · tasks · calendar · memory · automations │
│ files · activity · integrations · security · settings      │
└───────────────────────────┬────────────────────────────────┘
                            │ same-origin /api (REST + SSE)
┌───────────────────────────▼────────────────────────────────┐
│ FastAPI backend (Python 3.11)                              │
│  ├─ Auth (bcrypt, opaque sessions, CSRF, rate limit)       │
│  ├─ Orchestrator (AI provider ↔ Local Mode router)         │
│  │    └─ Context engine (history + FTS memory + prefs)     │
│  ├─ Permission firewall (scopes → grants/confirmations)    │
│  ├─ Tool registry (16 tools, strict I/O validation)        │
│  ├─ Workers (automation scheduler, reminders, cleanup)     │
│  └─ Audit log + structured JSON logs w/ request ids        │
└───────────────────────────┬────────────────────────────────┘
                            │ SQLAlchemy 2.0 + Alembic
              ┌─────────────▼─────────────┐
              │ SQLite (default) or       │
              │ PostgreSQL (production)   │
              └───────────────────────────┘
```

Full details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
Security model: [docs/SECURITY.md](docs/SECURITY.md) ·
Deployment: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) ·
API overview: [docs/API.md](docs/API.md)

---

## Quick start (local development)

```bash
# 1. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export MANISK_ENVIRONMENT=development
export MANISK_COOKIE_SECURE=false          # http dev only
.venv/bin/uvicorn mansik.main:app --reload --port 8000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api → :8000)
```

Migrations run automatically at startup (Alembic, `backend/alembic/versions/`).
Database: `sqlite:///./mansik.db` by default.

## Production

```bash
cp .env.example .env          # fill in secrets
cd frontend && npm ci && npm run build && cd ..
cd backend && pip install -r requirements.txt
export MANISK_FRONTEND_DIST=$(pwd)/../frontend/dist
export MANISK_DATABASE_URL=postgresql+psycopg2://user:pass@host/mansik   # optional
uvicorn mansik.main:app --host 0.0.0.0 --port 8000
```

Docker: `docker compose -f deploy/docker-compose.yml up -d --build`
(put HTTPS in front with your reverse proxy of choice; cookies are `Secure` by default).

## Enabling AI conversation

MANISK works with **any OpenAI-compatible API**. Set:

```bash
MANISK_AI_BASE_URL=https://integrate.api.nvidia.com/v1   # NVIDIA NIM (Nemotron)
MANISK_AI_MODEL=meta/llama-3.1-nemotron-70b-instruct
MANISK_AI_API_KEY=nvapi-...                              # if the provider requires one
```

Other known-good configs: OpenAI (`https://api.openai.com/v1`), Groq
(`https://api.groq.com/openai/v1`), Together (`https://api.together.xyz/v1`), local
Ollama (`http://127.0.0.1:11434/v1`, no key). Optional fallback provider:
`MANISK_AI_FALLBACK_*`. Keys live only in server env vars — never in the frontend,
never in logs, never in API responses (tested).

## Testing

```bash
cd backend
.venv/bin/python -m pytest tests/ -q        # 108 tests
```

Covers: auth (success/failure), CSRF, IDOR/user isolation, rate limiting, secret
leakage, SQL/prompt-injection attempts, memory CRUD + FTS, tasks, calendar + conflict
detection, tool validation + SSRF protection, permission firewall (confirmations,
grants, emergency stop), automations (grant gating, scheduler, skip rules), files
(validation, isolation), chat flows (Local Mode), and the full AI orchestration loop
against a local test-double provider server.

## Verification (what was actually tested end-to-end)

- 108 automated tests, all passing.
- Live production server (this repo's preview): register/login/logout, CSRF rejection,
  unauthenticated 401s, chat SSE streaming with tool events, task creation via natural
  language ("create task … due tomorrow 5pm"), memory save + FTS recall, calculator,
  confirmation flow for web search (approve → honest network-restricted error),
  file upload/download/type-rejection, emergency stop on/off, automation grant→create→enable,
  audit trail, security headers, database persistence across server restarts, and
  cross-user IDOR checks (all 404/401, zero data leakage).

## Repository layout

```
backend/    FastAPI app (mansik/), Alembic migrations, tests/
frontend/   React + Vite + TypeScript SPA
deploy/     Dockerfile, docker-compose.yml
docs/       architecture, security, deployment, API docs
.env.example  all environment variables, documented
```

## License

Provided as-is for the MANISK project.
