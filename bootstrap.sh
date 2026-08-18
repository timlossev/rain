#!/usr/bin/env bash
# Generate a .env with strong random secrets -- and a few interactively-
# chosen deployment settings -- on first run.
# Run this once before `docker compose up`. See bootstrap.py for details --
# this is a thin shell wrapper for hosts without Python on PATH. If a .env
# already exists it is left untouched; the prompts below only ever run on
# that first pass, have a default for every question (just press Enter),
# and are skipped entirely (every default used silently) when stdin isn't
# a real terminal -- piped/CI/non-interactive still works unattended.
#
# Bash 3.2 compatible on purpose (no `declare -A`, no `${var,,}`) --
# that's still what macOS ships by default, unlike this project's other
# shell usage which can assume a real Linux userland (Alpine images).
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

# One variable per possible override rather than an associative array
# (Bash 4+ only, and macOS still ships 3.2 by default) -- blank means
# "don't touch that line in .env.example".
postgres_url=""
s3_bucket=""
s3_region=""
s3_endpoint_url=""
s3_access_key_id=""
s3_secret_access_key=""
embed_worker=""
compose_profiles=""

ask_yes_no() {
    # $1 = prompt, $2 = default (y|n) -- echoes y or n
    local prompt="$1" default="$2" suffix answer
    if [[ "$default" == "y" ]]; then suffix="Y/n"; else suffix="y/N"; fi
    read -r -p "$prompt [$suffix] " answer || true
    answer="$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')"
    if [[ -z "$answer" ]]; then echo "$default"; return; fi
    if [[ "$answer" == "y" || "$answer" == "yes" ]]; then echo "y"; else echo "n"; fi
}

ask() {
    # $1 = prompt, $2 = default (optional) -- echoes the answer
    local prompt="$1" default="${2:-}" suffix answer
    if [[ -n "$default" ]]; then suffix=" [$default]"; else suffix=""; fi
    read -r -p "$prompt$suffix: " answer || true
    echo "${answer:-$default}"
}

test_postgres_connection() {
    # $1 = url -- prints "ok", "fail", or "unavailable" (docker missing).
    # No outer `timeout` wrapper -- not a portable command across every
    # platform this script runs on (notably absent by default on macOS
    # without coreutils) -- PGCONNECT_TIMEOUT already bounds the actual
    # connection attempt once the container's running; an image pull
    # taking a while is visible progress, not a silent hang.
    # psql's own stdout (the "SELECT 1" result table, on success) is
    # discarded -- the caller captures this function's output via
    # $(...), and psql's success-path output would otherwise get
    # concatenated with the "ok"/"fail" sentinel below, breaking the
    # caller's plain string comparison. Its stderr (the connection
    # error, on failure) is left alone so it's still shown to the user.
    if ! command -v docker >/dev/null 2>&1; then
        echo "unavailable"
        return
    fi
    if docker run --rm -e PGCONNECT_TIMEOUT=8 postgres:17-alpine psql "$1" -c "SELECT 1;" >/dev/null; then
        echo "ok"
    else
        echo "fail"
    fi
}

prompt_external_database() {
    # Loops on a failed connection test rather than giving up outright --
    # a typo in the URL is the common case, and re-prompting the one
    # field that's wrong is friendlier than aborting the whole run. A
    # failed test is never a hard stop either way: answering "y" below
    # saves the URL as given regardless of what the test said.
    local url result
    while true; do
        url="$(ask "External Postgres connection string (postgresql://user:password@host:5432/rain)")"
        if [[ -z "$url" ]]; then
            echo ""
            return
        fi
        echo "Testing the connection..." >&2
        result="$(test_postgres_connection "$url")"
        if [[ "$result" == "ok" ]]; then
            echo "Connected successfully." >&2
            echo "$url"
            return
        elif [[ "$result" == "unavailable" ]]; then
            echo "(Couldn't run a connection test -- docker isn't on PATH here. Continuing without one.)" >&2
            echo "$url"
            return
        fi
        if [[ "$(ask_yes_no "Could not connect with that URL. Continue with it anyway?" n)" == "y" ]]; then
            echo "$url"
            return
        fi
        # Otherwise loop back and ask for the URL again.
    done
}

if [[ -t 0 ]]; then
    echo ""
    echo "A few questions to configure this deployment (Enter accepts the default)."
    echo ""

    if [[ "$(ask_yes_no "Use the default setup -- RAIN's own built-in Postgres container, local document storage, and a separate worker container?" y)" == "n" ]]; then
        echo ""
        profiles="local-db,web-frontend,worker"

        if [[ "$(ask_yes_no "Use RAIN's own built-in Postgres container?" y)" == "n" ]]; then
            postgres_url="$(prompt_external_database)"
            profiles="${profiles/local-db,/}"
        fi

        if [[ "$(ask_yes_no "Store documents in S3 (or an S3-compatible service) instead of local disk?" n)" == "y" ]]; then
            s3_bucket="$(ask "S3 bucket name")"
            s3_region="$(ask "S3 region (blank is fine for a non-AWS endpoint)")"
            s3_endpoint_url="$(ask "S3 endpoint URL (blank for real AWS S3, set it for MinIO/etc.)")"
            s3_access_key_id="$(ask "S3 access key ID (blank to use an IAM role instead of a static key)")"
            if [[ -n "$s3_access_key_id" ]]; then
                s3_secret_access_key="$(ask "S3 secret access key")"
            fi
        fi

        if [[ "$(ask_yes_no "Merge the worker (syslog listener, rule engine, notifications) into the app container instead of running it separately?" n)" == "y" ]]; then
            embed_worker="true"
            profiles="${profiles/,worker/}"
        fi

        compose_profiles="$profiles"
    fi
else
    echo "Non-interactive session -- skipping deployment questions, using every default."
fi

# One sed invocation with output redirected to the new file (rather than
# in-place -i editing) -- sidesteps -i's BSD-vs-GNU flag differences
# entirely (BSD sed requires a space before the backup suffix, GNU
# doesn't accept one; simplest to just not use -i). '#' delimiter (not
# '/') since a Postgres URL or S3 endpoint URL commonly contains
# slashes; '&' and '#' in a value are escaped since both are meaningful
# to sed's replacement text/delimiter.
escape_value() {
    local v="$1"
    v="${v//&/\\&}"
    v="${v//#/\\#}"
    echo "$v"
}

sed_args=(-e "s#^POSTGRES_PASSWORD=.*\$#POSTGRES_PASSWORD=$(escape_value "$pg_password")#")
sed_args+=(-e "s#^APP_SECRET_KEY=.*\$#APP_SECRET_KEY=$(escape_value "$secret_key")#")
[[ -n "$postgres_url" ]] && sed_args+=(-e "s#^POSTGRES_URL=.*\$#POSTGRES_URL=$(escape_value "$postgres_url")#")
[[ -n "$s3_bucket" ]] && sed_args+=(-e "s#^S3_BUCKET=.*\$#S3_BUCKET=$(escape_value "$s3_bucket")#")
[[ -n "$s3_region" ]] && sed_args+=(-e "s#^S3_REGION=.*\$#S3_REGION=$(escape_value "$s3_region")#")
[[ -n "$s3_endpoint_url" ]] && sed_args+=(-e "s#^S3_ENDPOINT_URL=.*\$#S3_ENDPOINT_URL=$(escape_value "$s3_endpoint_url")#")
[[ -n "$s3_access_key_id" ]] && sed_args+=(-e "s#^S3_ACCESS_KEY_ID=.*\$#S3_ACCESS_KEY_ID=$(escape_value "$s3_access_key_id")#")
[[ -n "$s3_secret_access_key" ]] && sed_args+=(-e "s#^S3_SECRET_ACCESS_KEY=.*\$#S3_SECRET_ACCESS_KEY=$(escape_value "$s3_secret_access_key")#")
[[ -n "$embed_worker" ]] && sed_args+=(-e "s#^EMBED_WORKER=.*\$#EMBED_WORKER=$(escape_value "$embed_worker")#")
[[ -n "$compose_profiles" ]] && sed_args+=(-e "s#^COMPOSE_PROFILES=.*\$#COMPOSE_PROFILES=$(escape_value "$compose_profiles")#")

sed "${sed_args[@]}" "$example_path" > "$env_path"

echo ""
echo "Wrote $env_path."
echo "Edit RAIN_DOMAIN in .env if you have a public DNS name for automatic ACME certs."
echo "Next: docker compose up --build"
