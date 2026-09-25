# MANISK Deployment

## Option A — Render (one click)

The blueprint ([`render.yaml`](../render.yaml)) provisions a **PostgreSQL 16**
database (`0.1c-256mb`, Singapore region) and the Docker web service
(`0.5c-512mb`, Singapore), wires `MANISK_DATABASE_URL` for you, and attaches
a persistent disk for uploaded files.

1. **Merge the release PR into `main` first** — Render reads `render.yaml`
   from the repo's default branch and deploys that branch.
2. On [render.com](https://render.com) (sign in with GitHub):
   **New → Blueprint** → select this repository.
3. Confirm the two resources it will create: `mansik-db` (PostgreSQL) and
   `mansik` (web service).
4. When prompted, enter the three secrets:
   - `MANISK_AI_BASE_URL` — your OpenAI-compatible provider endpoint
   - `MANISK_AI_MODEL` — the model name
   - `MANISK_AI_API_KEY` — your provider key

   (`MANISK_SESSION_SECRET` is generated automatically; `MANISK_DATABASE_URL`
   is wired automatically. Optional: add `MANISK_TAVILY_API_KEY` later in the
   dashboard for better web search.)
5. Click **Apply**. The first build takes ~5–10 minutes. Alembic migrations
   run automatically at startup; the health check is `/api/health`.
6. Open the service URL (e.g. `https://mansik.onrender.com`). HTTPS and
   `Secure` cookies are automatic.

Every later push to `main` auto-deploys. Conversations/tasks/memories live
in PostgreSQL; uploaded files persist on the `mansik-files` disk.

Approximate cost: web `0.5c-512mb` + Postgres `0.1c-256mb` + 1 GB disk
(roughly $13–14/month total — confirm on
[render.com/pricing](https://render.com/pricing)). To trial at zero cost you
can switch the web service to the `free` plan in the dashboard (it sleeps
after ~15 min idle), but keep the paid database.

## Option B — Docker (recommended for self-hosting)

```bash
cp .env.example .env       # edit: session secret, AI provider, POSTGRES_PASSWORD
docker compose -f deploy/docker-compose.yml up -d --build
# health check
curl http://localhost:8000/api/health
```

The image builds the frontend, installs backend deps (incl. `psycopg2-binary`), runs
Alembic migrations at startup and serves API + SPA on `:8000`. Compose includes a
**PostgreSQL 16** database; `MANISK_DATABASE_URL` is wired to it automatically.
Files persist in the `mansik_data` volume.

Put HTTPS in front (Caddy/Traefik/nginx/Cloudflare) if exposed directly. Cookies are
`Secure` by default, so HTTPS is required for login to work from browsers.

## Option C — Bare metal / VM

```bash
# frontend
cd frontend && npm ci && npm run build
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export $(grep -v '^#' ../.env | xargs)     # or use a process manager
export MANISK_FRONTEND_DIST=/srv/mansik/frontend/dist
.venv/bin/uvicorn mansik.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Use PostgreSQL in production (`MANISK_DATABASE_URL=postgresql+psycopg2://…`);
SQLite is fine for single-user local instances only.

Systemd unit sketch:

```ini
[Unit]
Description=MANISK
After=network.target

[Service]
WorkingDirectory=/srv/mansik/backend
EnvironmentFile=/srv/mansik/.env
Environment=MANISK_FRONTEND_DIST=/srv/mansik/frontend/dist
ExecStart=/srv/mansik/backend/.venv/bin/uvicorn mansik.main:app --host 127.0.0.1 --port 8000
Restart=always
User=mansik

[Install]
WantedBy=multi-user.target
```

## Required environment variables

| Variable | Required | Purpose |
|---|---|---|
| `MANISK_SESSION_SECRET` | **yes (prod)** | session token derivation; random per-boot otherwise (logs users out on restart) |
| `MANISK_DATABASE_URL` | no | default `sqlite:///./mansik.db` |
| `MANISK_FRONTEND_DIST` | for SPA serving | path to `frontend/dist` |
| `MANISK_STORAGE_DIR` | no | file storage (default `./storage/files`) |

Optional integrations (honestly reported as unavailable until set):

| Variable | Unlocks |
|---|---|
| `MANISK_AI_BASE_URL` + `MANISK_AI_MODEL` (+ `MANISK_AI_API_KEY`) | AI conversation (any OpenAI-compatible API; e.g. NVIDIA NIM/Nemotron, OpenAI, Groq, Together, Ollama) |
| `MANISK_AI_FALLBACK_*` | automatic provider fallback |
| `MANISK_TAVILY_API_KEY` | premium web search (keyless DuckDuckGo fallback is on by default) |
| `MANISK_SMTP_*` | `email.send` tool |

## Scaling notes

- **Single process** (default): everything works as shipped (in-process scheduler,
  rate limiter).
- **Multiple uvicorn workers/processes**: run the app with workers, but start the
  scheduler in exactly ONE process (`python -c "from mansik.workers.scheduler import
  start_scheduler; from mansik.migrations import run_migrations; run_migrations();
  start_scheduler(); import time; [time.sleep(3600)]"`), and back the rate limiter
  with Redis (swap `mansik/security/rate_limit.py:RateLimiter` — the interface is two
  methods).
- **Health checks**: `GET /api/health` (liveness + DB), `GET /api/ready`.

## Upgrades

Migrations are versioned (`backend/alembic/versions/`); the app runs
`alembic upgrade head` at startup — never destroy data to deploy. For destructive
schema changes, write a new migration (Alembic batch mode is enabled for SQLite).

## Backups

- SQLite: copy `mansik.db` (+ WAL/SHM) and the storage dir while stopped or after
  `VACUUM INTO`.
- PostgreSQL: standard `pg_dump` + storage dir.

## Verifying a deployment

Run the mode-aware verifier against any live instance (local dev, preview, or
your public HTTPS deployment):

```bash
pip install httpx
python scripts/live_check.py https://your-app.onrender.com
```

It verifies: health/version, SPA serving, register/logout with server-side
session revocation, home summary with real counts, personalization, streaming
chat, tool execution through chat with **verified DB read-back**, memory
persistence, integrations honesty, permission scopes, the audit trail, and the
emergency stop (tools genuinely blocked while active). It adapts to Real AI
mode and Local Mode automatically, and tolerates cold starts. Exits non-zero
if any check fails.

On your phone (Android/Chrome): open the URL → register → chat
"remind me to buy milk tomorrow 5pm" → watch the tool card complete with a
verified result → check the Tasks page → Security → try the emergency stop.

