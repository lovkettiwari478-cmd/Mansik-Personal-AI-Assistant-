# MANISK production image — single container, API + built frontend.
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS backend
WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/mansik ./mansik
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# MANISK_DATABASE_URL must be provided by the deployment platform
# (PostgreSQL in production). MANISK_SESSION_SECRET and the AI provider
# vars are injected as secrets — never baked into the image.
ENV MANISK_FRONTEND_DIST=/app/frontend/dist \
    MANISK_STORAGE_DIR=/app/data/files \
    MANISK_COOKIE_SECURE=true

RUN mkdir -p /app/data/files
EXPOSE 8000
# Runs Alembic migrations at startup, then serves API + SPA on 0.0.0.0:8000
CMD ["uvicorn", "mansik.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
