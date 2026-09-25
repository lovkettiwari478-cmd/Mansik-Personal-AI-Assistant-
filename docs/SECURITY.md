# MANISK Security Model

## Threat-informed design

MANISK executes actions on behalf of a user (tasks, calendar, files, outbound web,
eventually email). The core security property: **no sensitive action happens without a
deliberate user decision**, and **every action is auditable**.

## Permission firewall

Risk classes (escalating): `read` → `low_risk_write` → `high_risk_write` →
`external_communication` → `financial` / `security` / `device_control`.

Decision flow for every tool execution:

1. **Emergency stop active** → block everything except reads (audited).
2. **Reads** → allowed for the authenticated owner.
3. **Standing denial** for the tool's scope → blocked.
4. **High-risk / external / financial / security / device** → require either
   - a standing grant the user created in Security settings, **or**
   - a fresh **confirmation**: single-use, expires in 10 minutes, bound to the
     requesting user, re-checked against emergency stop at execution time.
5. **Low-risk writes** (own tasks/memory/calendar) → allowed, audited.

Standing grants are required before an automation using a scope can even be enabled.

Scopes: `tasks:write`, `memory:write`, `calendar:write`, `files:write`, `notify`,
`tools:web`, `email:send`, `automation:manage` — each with a human label/description
surfaced in the Security page.

## Authentication & sessions

- Passwords: bcrypt cost 12; policy ≥10 chars + ≥2 character classes; credential-shaped
  content is refused in memories.
- Sessions: opaque 256-bit tokens; only SHA-256 hashes stored; HttpOnly + SameSite=Lax
  + Secure cookies; server-side revocation (logout, logout-all, password change revokes
  other sessions); device/session list visible to the user.
- Login failures are indistinguishable between unknown-email and wrong-password.

## Request hardening

- **CSRF**: double-submit token (non-HttpOnly cookie + `X-CSRF-Token` header, compared
  with `secrets.compare_digest`) on every unsafe method, on top of SameSite=Lax.
- **Rate limiting**: per-IP sliding window (auth 10/min, chat 20/min, default 240/min);
  in-process by default, Redis-swappable for multi-worker deployments.
- **Headers**: strict CSP (`default-src 'self'` …), `X-Frame-Options: DENY`,
  `nosniff`, Referrer-Policy, Permissions-Policy, COOP/CORP, `X-Request-ID`.
- **Errors**: user-safe messages with request ids; stack traces only in server logs.

## Data isolation

Every user-owned row carries `user_id` (FK, NOT NULL, indexed). Every read/write
re-checks ownership and returns **404** for foreign resources. Verified by dedicated
IDOR tests across all resource types (tasks, memories, events, conversations, files,
automations, confirmations, sessions, notifications, activity) and by live two-user
probes against the deployed instance.

## Injection resistance

- SQL: SQLAlchemy parameter binding everywhere; raw FTS5 queries use bound parameters
  and a sanitized MATCH expression.
- XSS: React escaping by default; the only rich-text rendering is a tiny
  token-substitution renderer that never builds HTML strings.
- Prompt injection: tool outputs are wrapped as **untrusted data** with explicit
  instructions; the model cannot execute anything by talking; sensitive tools are
  gated by the firewall regardless of what the model says; tool output size is capped.
- SSRF: `web.fetch` resolves DNS and blocks private/loopback/link-local/reserved
  addresses (including cloud metadata 169.254.169.254), non-http schemes, credentials
  in URLs, non-standard ports.
- Calculator: AST whitelist (no `eval`), blocks `__import__`, attribute access,
  huge exponents, string literals.

## Secrets

- All credentials come from environment variables (`MANISK_*`), documented in
  `.env.example`.
- Never returned by any API (`/api/status` exposes only booleans + model names —
  covered by leakage tests), never logged (logging layer redacts password/api-key/
  token/secret/authorization/cookie keys).

## Account & recovery

Self-service: register, login, logout, logout-all, password change (revokes other
sessions), session listing/revocation. **Face Lock / Master Key Card recovery are not
implemented** — real biometrics require platform APIs (WebAuthn planned); faking them
would be worse than not having them.

## Memory privacy

Memory is user-controlled: view / edit / delete / search in the UI, global on/off
switch (also stops retrieval), credential-shaped content refused, memories used in a
chat turn are surfaced as attribution chips, conversation history and long-term memory
are separate stores, and auto-memory only happens as a visible `memory.save` tool call
in AI mode — never silently.

## What is NOT claimed

"Secure" is not an absolute. Verified at v0.1.0: the behaviors above are covered by
108 automated tests and live probes. Not yet done: external penetration testing,
WebAuthn/2FA, per-IP lockout persistence across workers (Redis), audit log tamper
resistance (append-only store), and encryption at rest beyond the OS level.
