# syntax=docker/dockerfile:1


FROM python:3.12-slim AS builder

WORKDIR /build


COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt



FROM python:3.12-slim AS runtime


RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app


COPY --from=builder /install /usr/local


COPY . .


RUN mkdir -p /app/static/uploads /app/data \
 && chown -R appuser:appgroup /app

USER appuser

# Gunicorn settings
ENV PORT=8000 \
    WORKERS=2 \
    TIMEOUT=120 \
    APP_ENV=production \
    DATABASE=/app/data/collectorshop.sqlite3

EXPOSE 8000


CMD python -c "from app import init_db; init_db()" \
 && exec gunicorn \
      --bind "0.0.0.0:${PORT}" \
      --workers "${WORKERS}" \
      --timeout "${TIMEOUT}" \
      --access-logfile - \
      --error-logfile - \
      "app:app"
