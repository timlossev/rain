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

ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER rain
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD wget -q -O- http://127.0.0.1:8000/healthz || exit 1

CMD ["rain-web"]
