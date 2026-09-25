# MANISK API Overview

Base URL: same origin, prefix `/api`. Auth: `mansik_session` cookie (HttpOnly) +
`mansik_csrf` cookie echoed as `X-CSRF-Token` header on unsafe methods.
Errors: `{"error": {"code", "message", "request_id"}}`.

## Status
- `GET /api/health` — liveness + DB (no auth)
- `GET /api/status` — subsystem status, honest booleans (auth)
- `GET /api/tools` — tool catalog with risk/scope/availability
- `GET /api/integrations` — integration status + required env vars

## Auth
- `POST /api/auth/register` `{email, password, display_name}` → 201 + cookies
- `POST /api/auth/login` `{email, password}`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/auth/change-password` `{current_password, new_password}`
- `GET /api/auth/sessions` · `DELETE /api/auth/sessions/{id}` · `POST /api/auth/logout-all`

## Chat (SSE)
- `POST /api/chat` `{conversation_id?, message}` → `text/event-stream`
  Events: `meta` (mode: ai|local, memories_used), `tool_start`, `tool_end`
  (success, summary, trimmed output), `confirmation_required` (confirmation_id,
  tool, risk, reason, params), `delta` (text), `error`, `done` (message_id,
  conversation_id, execution_summary).
- `GET /api/confirmations/pending`
- `POST /api/confirmations/{id}/approve` → executes tool, returns result + continuation
- `POST /api/confirmations/{id}/deny`

## Conversations
- `GET /api/conversations` · `POST /api/conversations`
- `GET /api/conversations/{id}/messages` · `DELETE /api/conversations/{id}`

## Memory
- `GET /api/memories?kind=` · `POST /api/memories` `{content, kind, importance}`
- `PATCH /api/memories/{id}` · `DELETE /api/memories/{id}`
- `POST /api/memories/search` `{query, limit?}` (FTS5)

## Tasks
- `GET /api/tasks?status=` · `POST /api/tasks` `{title, notes?, priority, due_at?, recurrence?, remind_minutes_before?}`
- `PATCH /api/tasks/{id}` · `DELETE /api/tasks/{id}`
- statuses: `todo|in_progress|done|cancelled`; priorities: `low|medium|high|urgent`

## Calendar
- `GET /api/calendar?days=` · `POST /api/calendar` `{title, starts_at, ends_at, location?, all_day?, recurrence?, reminder_minutes?}`
- `PATCH /api/calendar/{id}` · `DELETE /api/calendar/{id}`

## Automations
- `GET /api/automations` · `POST /api/automations` `{name, trigger_type:
  interval|daily_at, trigger_config, action_tool, action_params, enabled}`
  — enabling requires a standing grant for the tool's scope
- `PATCH /api/automations/{id}` (incl. enable/disable) · `DELETE /api/automations/{id}`
- `GET /api/automations/{id}/runs` — execution log

## Files
- `GET /api/files` · `POST /api/files` (multipart `file`)
- `GET /api/files/{id}/download` · `DELETE /api/files/{id}`

## Security
- `GET /api/security/permissions` — scope catalogue + grant state
- `POST /api/security/permissions` `{scope, allowed, note?}` · `DELETE /api/security/permissions/{scope}`
- `GET|POST /api/security/emergency-stop` `{enabled}`

## Activity & notifications
- `GET /api/activity?category=&limit=` — the user's audit trail
- `GET /api/notifications` · `POST /api/notifications/{id}/read` · `POST /api/notifications/read-all`

## Settings & knowledge graph
- `GET|PATCH /api/settings` (display_name, timezone, theme, memory_enabled)
- `GET|POST /api/graph/entities` · `DELETE /api/graph/entities/{id}`
- `POST /api/graph/relations` `{from_entity_id, to_entity_id, relation_type}`
