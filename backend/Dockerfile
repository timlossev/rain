# Multi-stage build: compiler toolchain never reaches the final image.
FROM python:3.12-alpine AS builder

# xmlsec1-dev (+ its own libxml2-dev/libxslt-dev) is only needed to build
# the `xmlsec` Python package's C extension, which python3-saml uses for
# XML-DSig signature verification on SAML responses -- hand-rolling that
# instead of using an established toolkit isn't worth the risk for
# something this security-sensitive.
RUN apk add --no-cache build-base libffi-dev xmlsec-dev libxml2-dev libxslt-dev

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

# A plain `RUN pip install --upgrade pip` is cached by Docker on the
# instruction text alone -- once built, every later `docker compose
# build` would keep reinstalling that SAME pip forever, regardless of
# what's actually newest on PyPI, unless something upstream of it also
# happened to change. ADD with a remote URL is the documented exception:
# Docker re-fetches it on every build and only invalidates the cache
# from here down when the response actually differs -- i.e. exactly
# when pip has shipped a new release since the last build, and never
# otherwise. That's what actually gets "upgrade pip to latest on every
# build" instead of "upgrade pip to latest the first time, then never
# again."
ADD https://pypi.org/pypi/pip/json /tmp/pip-latest.json

RUN python -m venv /venv \
 # >=26.1.2 explicitly, not just --upgrade to "whatever's latest today" --
 # CVE-2026-8643 (pip could extract console_scripts/gui_scripts entry
 # points outside the installation directory) was fixed there, and pip
 # itself ships inside /venv in the final image (copied wholesale below),
 # so an unpinned floor could silently regress under image layer caching.
 && /venv/bin/pip install --no-cache-dir --upgrade "pip>=26.1.2" \
 && /venv/bin/pip install --no-cache-dir .

FROM python:3.12-alpine

# xmlsec (runtime shared libs only, no -dev/compiler) for the `xmlsec`
# package built above -- see the builder stage's comment.
RUN apk add --no-cache xmlsec

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
