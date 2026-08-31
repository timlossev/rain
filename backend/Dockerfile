# Multi-stage build: compiler toolchain never reaches the final image.
FROM python:3.12-alpine AS builder

# `apk upgrade` first: this stage's FROM tag is a floating `python:3.12-
# alpine` (no digest pin -- see the final stage's own tag for why), so
# its layers reflect whenever Docker Hub last rebuilt it, not today.
# Upgrading before installing anything pulls every already-present Alpine
# package -- openssl included -- forward to whatever the Alpine package
# index actually has right now, closing system-library CVEs that may
# predate that last rebuild regardless of how fresh the tag looks. Covers
# the Aug 2026 OpenSSL batch (CVE-2026-54874, 63072, 63075, 63076, 18798,
# 14457; fixed upstream in 3.0.22/3.4.7/3.5.8/3.6.4/4.0.2) at build time,
# same "always take latest, not a stale pin" reasoning as the pip ADD
# trick below.
#
# xmlsec1-dev (+ its own libxml2-dev/libxslt-dev) is only needed to build
# the `xmlsec` Python package's C extension, which python3-saml uses for
# XML-DSig signature verification on SAML responses -- hand-rolling that
# instead of using an established toolkit isn't worth the risk for
# something this security-sensitive.
RUN apk upgrade --no-cache \
 && apk add --no-cache build-base libffi-dev xmlsec-dev libxml2-dev libxslt-dev

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
 # The same floor also already clears CVE-2026-6357 (insecure self-update
 # deserialization) and CVE-2026-13346 (doubly-encoded index URLs could
 # place files outside the install dir) -- both were fixed at 26.1, before
 # this floor's 26.1.2, and the ADD-triggered rebuild above means we're
 # never actually stuck on 26.1.2 itself: every build re-checks PyPI and
 # takes whatever is newest, so later pip CVEs get picked up the same way
 # without this floor needing to chase each one by number.
 && /venv/bin/pip install --no-cache-dir --upgrade "pip>=26.1.2" \
 && /venv/bin/pip install --no-cache-dir .

FROM python:3.12-alpine

# Same package-freshness reasoning as the builder stage's `apk upgrade`
# above (this is a separate, later `FROM` of the same floating tag, so it
# needs its own upgrade -- nothing carries over between stages except
# what's explicitly COPY --from'd).
RUN apk upgrade --no-cache

# xmlsec (runtime shared libs only, no -dev/compiler) for the `xmlsec`
# package built above -- see the builder stage's comment.
RUN apk add --no-cache xmlsec

# The base image's own system-level pip (ensurepip, baked into this
# tag's system Python outside our venv) is never actually used here --
# PATH below always resolves pip/python to /venv/bin first, and the
# builder stage's own upgrade only ever touched *that* venv's pip, not
# this stage's separate system one. Left in place, an image scanner
# still walks the filesystem and flags whatever (likely older) pip
# version this tag happened to ship, on a copy nothing ever calls --
# the likeliest explanation for a pip CVE (e.g. CVE-2026-6357) still
# showing up in a scan despite the venv's own pip already being
# >=26.1.2. Removing it outright, rather than upgrading a copy that's
# dead weight either way, closes that finding and trims the image at
# the same time. No network access needed (unlike the venv's own
# PyPI-triggered upgrade above), so this holds even in an air-gapped
# build. setuptools/wheel come along for the same reason -- the same
# unused-system-copy story applies to their own CVEs.
RUN python3 -m pip uninstall -y pip setuptools wheel 2>/dev/null || true

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
