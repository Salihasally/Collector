# syntax=docker/dockerfile:1

# ─── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user for security
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Fix Windows CRLF line endings on entrypoint.sh (breaks bash on Linux)
# and make it executable
RUN apt-get update && apt-get install -y --no-install-recommends dos2unix \
 && dos2unix /app/entrypoint.sh \
 && chmod +x /app/entrypoint.sh \
 && apt-get remove -y dos2unix && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Pre-create writable directories
# /tmp/data  → SQLite database (/tmp is always writable on Cloud Run)
# /app/static/uploads → seller image uploads
RUN mkdir -p /app/static/uploads /tmp/data \
 && chown -R appuser:appgroup /app /tmp/data

USER appuser

# Cloud Run injects PORT automatically; DATABASE uses /tmp (always writable)
ENV PORT=8000 \
    WORKERS=2 \
    TIMEOUT=120 \
    APP_ENV=production \
    DATABASE=/tmp/data/collectorshop.sqlite3

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
