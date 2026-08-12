# Postgres 16 on Alpine with pgvector compiled in.
#
# pgvector is installed now (Milestone 1) even though nothing uses it yet,
# so the future LLM keyword/vector search hook is a migration away instead
# of a base-image change. Build stage is discarded, so the final image
# carries no compiler toolchain.

FROM postgres:16-alpine AS builder

RUN apk add --no-cache build-base clang llvm19 git postgresql-dev

RUN git clone --branch v0.7.4 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector OPTFLAGS="" \
 && make -C /tmp/pgvector install

FROM postgres:16-alpine

COPY --from=builder /usr/local/lib/postgresql/vector.so /usr/local/lib/postgresql/vector.so
COPY --from=builder /usr/local/share/postgresql/extension/vector* /usr/local/share/postgresql/extension/
