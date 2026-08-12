# Postgres 16 on Alpine with pgvector compiled in.
#
# pgvector is installed now (Milestone 1) even though nothing uses it yet,
# so the future LLM keyword/vector search hook is a migration away instead
# of a base-image change. Build stage is discarded, so the final image
# carries no compiler toolchain.
#
# postgres:16-alpine builds Postgres from source (not from Alpine's apk
# postgresql packages), and a standard `make install` already puts
# pg_config and the server headers under /usr/local -- which is already
# on PATH in this image. So the only apk packages pgvector's build needs
# are a compiler toolchain and git; no postgresql-dev package (whose exact
# name would have to match Alpine's version-pinned postgresql16-dev
# naming anyway) is required or installed.

FROM postgres:16-alpine AS builder

RUN apk add --no-cache build-base git

RUN git clone --branch v0.7.4 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector OPTFLAGS="" \
 && make -C /tmp/pgvector install

FROM postgres:16-alpine

COPY --from=builder /usr/local/lib/postgresql/vector.so /usr/local/lib/postgresql/vector.so
COPY --from=builder /usr/local/share/postgresql/extension/vector* /usr/local/share/postgresql/extension/
