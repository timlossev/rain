#!/usr/bin/env bash
# Generate a .env with strong random secrets on first run.
# Run this once before `docker compose up`. See bootstrap.py for details --
# this is a thin POSIX shell wrapper for hosts without Python on PATH.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
env_path="$root/.env"
example_path="$root/.env.example"

if [[ -f "$env_path" ]]; then
    echo ".env already exists at $env_path, leaving it untouched."
    exit 0
fi

if [[ ! -f "$example_path" ]]; then
    echo "missing template: $example_path" >&2
    exit 1
fi

gen_secret() {
    # $1 = number of random bytes
    openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'
}

pg_password="$(gen_secret 32)"
secret_key="$(gen_secret 48)"

sed -e "s#POSTGRES_PASSWORD=#POSTGRES_PASSWORD=${pg_password}#" \
    -e "s#APP_SECRET_KEY=#APP_SECRET_KEY=${secret_key}#" \
    "$example_path" > "$env_path"

echo "Wrote $env_path with freshly generated secrets."
echo "Edit RAIN_DOMAIN in .env if you have a public DNS name for automatic ACME certs."
echo "Next: docker compose up --build"
