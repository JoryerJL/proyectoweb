#!/bin/sh
# Container entrypoint: wait for the database, prepare the app, then run the command.
set -eu

echo "[entrypoint] Waiting for database at ${DB_HOST:-localhost}:${DB_PORT:-5432}..."
python - <<'PY'
import os
import sys
import time

import psycopg

dsn = {
    "dbname": os.environ.get("DB_NAME", "canaco"),
    "user": os.environ.get("DB_USER", "canaco"),
    "password": os.environ.get("DB_PASSWORD", "canaco"),
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "connect_timeout": 3,
}
for attempt in range(1, 61):
    try:
        psycopg.connect(**dsn).close()
        print("[entrypoint] Database is ready.")
        sys.exit(0)
    except psycopg.OperationalError as exc:
        print(f"[entrypoint] Attempt {attempt}/60 failed: {exc}".strip())
        time.sleep(2)
print("[entrypoint] Database did not become ready in time.", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] Applying migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Setting site domain (no-op without DJANGO_SITE_DOMAIN)..."
python manage.py set_site_domain

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

# Optional demo content; seed_news is idempotent.
case "${RUN_SEED:-0}" in
  1|true|TRUE|yes|on)
    echo "[entrypoint] Seeding demo news..."
    python manage.py seed_news
    ;;
esac

echo "[entrypoint] Starting: $*"
exec "$@"
