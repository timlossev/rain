# Multi-stage build: compiler toolchain never reaches the final image.
FROM python:3.12-alpine AS builder

RUN apk add --no-cache build-base libffi-dev

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /venv \
 && /venv/bin/pip install --no-cache-dir --upgrade pip \
 && /venv/bin/pip install --no-cache-dir .

FROM python:3.12-alpine

RUN addgroup -S rain \
 && adduser -S rain -G rain \
 && mkdir -p /data/uploads \
 && chown -R rain:rain /data/uploads

COPY --from=builder /venv /venv
WORKDIR /app
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER rain
EXPOSE 8000

# Shell form (not a JSON array) on purpose -- APP_PORT is only known at
# container-run time (docker-compose.yml's app service sets it), and
# shell form is what lets $APP_PORT actually expand here; a JSON-array
# CMD would pass the literal string "$APP_PORT" to wget instead.
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD wget -q -O- http://127.0.0.1:${APP_PORT:-8000}/healthz || exit 1

CMD ["rain-web"]
