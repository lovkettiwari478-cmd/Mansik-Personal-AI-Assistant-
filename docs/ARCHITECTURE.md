# MANISK Architecture

## Principles

1. **The model never executes anything.** The LLM (or the Local Mode router) only
   *proposes* tool calls. Every proposal passes through the permission firewall and a
   hardened executor (schema validation → timeout → output validation → audit).
2. **Honesty over demos.** Unconfigured integrations report themselves as unavailable.
   Local Mode never pretends to be intelligent conversation.
3. **Isolation by construction.** Every user-owned table has `user_id` NOT NULL + FK +
   index; every query filters by the authenticated user; ownership is re-checked on
   every mutation (404 for foreign resources, never 403-with-existence-leak).
4. **Observability everywhere.** Structured JSON logs with request/execution ids, plus
   an auditable event log the user can read.

## Backend layout

```
backend/mansik/
├── main.py            app factory, middleware stack, SPA serving
├── config.py          pydantic-settings, risk taxonomy, public_status()
├── database.py        engine/session management (SQLite WAL / PostgreSQL)
├── models.py          SQLAlchemy 2.0 models + FTS5 DDL
├── migrations.py      programmatic Alembic runner (startup)
├── errors.py          AppError hierarchy + safe handlers (no stack traces to users)
├── security/
│   ├── passwords.py   bcrypt (cost 12) + password policy
│   ├── auth.py        sessions (opaque tokens, SHA-256 at rest), CSRF, require_auth
│   ├── rate_limit.py  sliding-window limiter (Redis-swappable interface)
│   └── middleware.py  request-id, execution-id, security headers
├── observability/     JSON logging (secret redaction), audit log writer
├── permissions/       scopes.py (capability catalogue), firewall.py (decision engine)
├── tools/             registry + 16 tools (see Tool architecture)
├── memory/service.py  FTS5 retrieval (SQLite) / ILIKE (PostgreSQL)
├── ai/
│   ├── providers.py   OpenAI-compatible provider(s): chat + stream, retry, fallback
│   ├── context.py     context engine (history, memories, tasks, time, prefs)
│   ├── prompt.py      hardened system prompt (tool protocol, injection rules)
│   ├── local_router.py deterministic intent routing (Local Mode)
│   └── orchestrator.py the execution pipeline (below)
├── workers/scheduler.py  automations, reminders, confirmation expiry
├── files/service.py   validation, random names, text extraction
└── api/               routers: auth, chat(+confirmations), conversations, memories,
                       tasks, calendar, automations, files, activity, security,
                       settings(+graph), status(+health/tools/integrations)
```

## The orchestration pipeline

```
user message
   │
   ▼
persist user message ──► context engine ──► system prompt
   │                        (recent messages, FTS memory hits, open tasks,
   │                         current time, user preferences)
   ▼
PLAN  ── AI mode: provider.stream_chat() with a JSON tool protocol
   │      ({"reply": ...} or {"tool_calls": [...]}, max 3 iterations)
   └─ Local Mode: deterministic regex intent router → same tool_calls shape
   │
   ▼
for each proposed call:
   PERMISSION FIREWALL
     ├─ emergency stop active?        → block (audit)
     ├─ risk == read                  → allow
     ├─ standing denial for scope     → block (audit)
     ├─ risk ∈ {high-risk write, external comm, financial, security, device}
     │    ├─ standing grant exists    → allow (audit)
     │    └─ else                     → create Confirmation, pause turn
     └─ low-risk write                → allow (audit)
   │
   ▼
EXECUTOR (tools/base.execute_tool)
   strict param validation → asyncio.wait_for(timeout) → output size check → audit
   │
   ▼
tool outputs fed back as UNTRUSTED DATA (prompt-injection hardened)
   │
   ▼
RESPONSE ── AI: streamed deltas · Local: deterministic summary
   │
   ▼
persist assistant message with execution summary (never chain-of-thought)
```

SSE events: `meta` (mode, memories used) · `tool_start` · `tool_end` (summary, trimmed
output) · `confirmation_required` · `delta` · `error` · `done` (execution summary).

## Tool architecture

Every tool: unique id · human description · category · **risk class** · permission
scope (or none) · timeout · strict Pydantic input model (extra=forbid) ·
JSON-serializable, size-capped output · audit row per execution. There is
deliberately **no** shell/code-execution tool. The AST-whitelisted calculator is the
only "code-like" tool and accepts nothing but numbers, arithmetic and a math-function
allowlist.

## Data model (see models.py)

users, user_settings, auth_sessions, conversations, messages, memories (+FTS5 index
and triggers), tasks, events, automations, automation_runs, permission_grants,
confirmations, audit_logs, stored_files, entities, entity_relations, notifications.

All timestamps are timezone-aware UTC (`AwareDateTime` normalizes SQLite's naive
round-trip). Soft deletes (`deleted_at`) for user data; hard delete for sessions.

## Frontend

React 18 + TypeScript + Vite, no UI framework (70 KB gzipped). Mobile-first: bottom
nav + drawer under 900px, sidebar on desktop. The chat consumes SSE over
`fetch` + `ReadableStream` (POST with CSRF header). All state via small contexts
(auth, toasts, system status, notifications). Empty/error/loading states everywhere;
the Local Mode banner is always visible when no AI provider is configured.

## Workers

A single daemon-thread scheduler ticks every 30s: expires stale confirmations, sends
task/event reminder notifications, and executes due automations (each run logged;
skipped if the user's standing grant was revoked or emergency stop is active). For
multi-process deployments run exactly one scheduler instance (documented in
DEPLOYMENT.md).
