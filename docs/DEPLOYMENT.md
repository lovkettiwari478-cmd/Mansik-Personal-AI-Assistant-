# MANISK Deployment

## Option A — Docker (recommended)

```bash
cp .env.example .env       # edit: session secret, AI provider, etc.
docker compose -f deploy/docker-compose.yml up -d --build
# health check
curl http://localhost:8000/api/health
```

The image builds the frontend, installs backend deps, runs Alembic migrations at
startup and serves API + SPA on `:8000`. Data persists in the `mansik_data` volume
(SQLite at `/app/data/mansik.db`, files at `/app/data/files`).

Put HTTPS in front (Caddy/Traefik/nginx/Cloudflare). Cookies are `Secure` by default,
so HTTPS is required for login to work from browsers.

### PostgreSQL

Uncomment the `db` service in `deploy/docker-compose.yml` and set:

```
MANISK_DATABASE_URL=postgresql+psycopg2://mansik:CHANGE_ME@db:5432/mansik
```

Add `psycopg2-binary` to `backend/requirements.txt`. Migrations run automatically.

## Option B — Bare metal / VM

```bash
# frontend
cd frontend && npm ci && npm run build
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export $(grep -v '^#' ../.env | xargs)     # or use a process manager
export MANISK_FRONTEND_DIST=/srv/mansik/frontend/dist
.venv/bin/uvicorn mansik.main:app --host 0.0.0.0 --port 8000 --workers 1
```

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
