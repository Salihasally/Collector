# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Non-root user for security
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Install dependencies directly — no multi-stage prefix tricks
# This guarantees gunicorn ends up in /usr/local/bin which is always in PATH
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir gunicorn \
 && which gunicorn \
 && gunicorn --version

# Copy application source
COPY . .

# Fix Windows CRLF line endings on entrypoint.sh (breaks bash on Linux)
RUN apt-get update && apt-get install -y --no-install-recommends dos2unix \
 && dos2unix /app/entrypoint.sh \
 && chmod +x /app/entrypoint.sh \
 && apt-get remove -y dos2unix && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Pre-create writable directories
RUN mkdir -p /app/static/uploads /tmp/data \
 && chown -R appuser:appgroup /app /tmp/data

USER appuser

ENV PORT=8000 \
    WORKERS=2 \
    TIMEOUT=120 \
    APP_ENV=production \
    DATABASE=/tmp/data/collectorshop.sqlite3

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
