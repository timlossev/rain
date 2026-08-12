# pgvector's project publishes official images with the extension already
# compiled in (github.com/pgvector/pgvector, Docker Hub pgvector/pgvector),
# built FROM the official postgres image with the same entrypoint/env vars
# (POSTGRES_USER/PASSWORD/DB) -- so this is a drop-in replacement for
# postgres:17, no build stage needed. Those images are Debian-based
# (trixie/bookworm), not Alpine -- pgvector doesn't publish Alpine
# variants, and compiling it ourselves against postgres:16-alpine turned
# out to be a real maintenance burden (two separate build failures, see
# git history), so the db image trades the Alpine-everywhere pattern used
# for app/worker/caddy for "officially maintained, zero build step" here.
#
# pgvector is installed now (Milestone 1) even though nothing uses it yet,
# so the future LLM keyword/vector search hook is a migration away instead
# of a base-image change.
FROM pgvector/pgvector:pg17-trixie
