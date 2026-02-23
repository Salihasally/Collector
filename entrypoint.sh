#!/bin/sh
set -e

echo "=== Collector.shop startup ==="

# Cloud Run injects PORT automatically; fall back to 8000
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-2}"
TIMEOUT="${TIMEOUT:-120}"
DATABASE="${DATABASE:-/tmp/data/collectorshop.sqlite3}"

echo "→ PORT=$PORT"
echo "→ DATABASE=$DATABASE"
echo "→ Python: $(python --version)"
echo "→ Gunicorn: $(gunicorn --version)"

# Ensure the data directory exists and is writable
DB_DIR="$(dirname "$DATABASE")"
echo "→ Creating DB directory: $DB_DIR"
mkdir -p "$DB_DIR"

# Verify it's writable
if ! touch "$DB_DIR/.write_test" 2>/dev/null; then
  echo "ERROR: $DB_DIR is not writable — cannot start"
  exit 1
fi
rm -f "$DB_DIR/.write_test"
echo "→ DB directory is writable"

# Initialise / migrate the database
echo "→ Initialising database..."
python -c "
import sys
sys.stdout.flush()
from app import init_db
init_db()
print('Database init complete')
sys.stdout.flush()
"
echo "→ Database ready"

# Start Gunicorn — exec replaces shell so Cloud Run signals work correctly
echo "→ Starting Gunicorn on 0.0.0.0:${PORT}"
exec gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}" \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  "app:app"
