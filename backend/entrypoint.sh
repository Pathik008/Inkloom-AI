#!/usr/bin/env sh
set -e

echo "[INKLOOM BOOT] Starting Inkloom AI backend..."
echo "[INKLOOM BOOT] Running database migrations (alembic upgrade head)..."
alembic upgrade head

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
    echo "[INKLOOM BOOT] SEED_DEMO_DATA=true detected. Running seed script..."
    python -m app.scripts.seed_demo || echo "[INKLOOM BOOT] Warning: Seed script returned non-zero exit code"
fi

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
echo "[INKLOOM BOOT] Launching uvicorn on ${HOST}:${PORT}..."
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --proxy-headers --forwarded-allow-ips "*"
