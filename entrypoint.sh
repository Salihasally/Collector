#!/bin/sh
set -e

echo "=== Collector.shop startup ==="

# Cloud Run injects PORT automatically; fall back to 8000
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-2}"
TIMEOUT="${TIMEOUT:-120}"

echo "→ PORT=$PORT"
echo "→ DATABASE=$DATABASE"

# Ensure the data directory exists and is writable
# (Cloud Run filesystem is writable but ephemeral unless a volume is mounted)
mkdir -p "$(dirname "$DATABASE")"

# Initialise / migrate the database
echo "→ Initialising database..."
python -c "from app import init_db; init_db()"
echo "→ Database ready"

# Start Gunicorn
echo "→ Starting Gunicorn on 0.0.0.0:${PORT}"
exec gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}" \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  "app:app"
