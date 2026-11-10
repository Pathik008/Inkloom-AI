#!/usr/bin/env sh
set -e

echo "[INKLOOM BOOT] Starting Inkloom AI backend..."

# Bounded database readiness retry loop (max 30s) before migrations
echo "[INKLOOM BOOT] Verifying database readiness..."
python - << 'EOF'
import sys
import time
from sqlalchemy import create_engine, text
from app.core.config import settings

max_retries = 15
retry_interval = 2
uri = settings.sqlalchemy_database_uri

print(f"[INKLOOM BOOT] Probing database connection (max {max_retries} attempts, {max_retries * retry_interval}s timeout)...")

engine = create_engine(
    uri,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3} if uri.startswith("postgresql") else {},
)

for attempt in range(1, max_retries + 1):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"[INKLOOM BOOT] Database is ready on attempt {attempt}.")
        sys.exit(0)
    except Exception as exc:
        print(f"[INKLOOM BOOT] Attempt {attempt}/{max_retries}: Database not ready yet ({exc.__class__.__name__}). Retrying in {retry_interval}s...")
        if attempt < max_retries:
            time.sleep(retry_interval)

print(f"[INKLOOM BOOT] FATAL: Database failed to respond after {max_retries * retry_interval} seconds. Aborting startup.", file=sys.stderr)
sys.exit(1)
EOF

echo "[INKLOOM BOOT] Running database migrations (alembic upgrade head)..."
alembic upgrade head

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
    echo "[INKLOOM BOOT] SEED_DEMO_DATA=true detected. Running seed script..."
    python -m app.scripts.seed_demo || {
        echo "[INKLOOM BOOT] FATAL: Seed script failed with non-zero exit code. Aborting startup." >&2
        exit 1
    }
fi

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
echo "[INKLOOM BOOT] Launching uvicorn on ${HOST}:${PORT}..."
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}" --proxy-headers --forwarded-allow-ips "*"
