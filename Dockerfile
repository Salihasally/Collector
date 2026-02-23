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

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Pre-create writable directories
# /app/data  → SQLite database (mount a volume here for persistence)
# /app/static/uploads → seller image uploads
RUN mkdir -p /app/static/uploads /app/data \
 && chown -R appuser:appgroup /app

USER appuser

# Cloud Run will inject PORT automatically; we default to 8000
ENV PORT=8000 \
    WORKERS=2 \
    TIMEOUT=120 \
    APP_ENV=production \
    DATABASE=/app/data/collectorshop.sqlite3

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
