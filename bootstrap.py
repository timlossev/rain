#!/usr/bin/env python3
"""Generate a .env with strong random secrets -- and a few interactively-
chosen deployment settings -- on first run.

Run this once before `docker compose up`. If a .env already exists it is
left untouched (so restarts/upgrades keep working with the same secrets
and settings) -- the prompts below only ever run once, on that first
pass. Every question has a sensible default (just press Enter), and if
stdin isn't a real terminal (piped/CI/non-interactive) the prompts are
skipped entirely and every default is used silently, so this still works
unattended. Everything asked here can also just be hand-edited in .env
afterwards -- see the comments in .env.example, which this script starts
from either way.
"""
from __future__ import annotations

import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"

# Every KEY=... line this script might override appears exactly once in
# .env.example, so a single anchored regex substitution per key is safe
# regardless of whether that line already carries a default value
# (COMPOSE_PROFILES, EMBED_WORKER) or is blank (POSTGRES_URL, S3_*).
_LINE_RE = "^{key}=.*$"


def _set(text: str, key: str, value: str) -> str:
    return re.sub(_LINE_RE.format(key=re.escape(key)), f"{key}={value}", text, count=1, flags=re.MULTILINE)


def _interactive() -> bool:
    return sys.stdin.isatty()


def _ask_yes_no(prompt: str, *, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{suffix}] ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def _ask(prompt: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _test_postgres_connection(url: str) -> bool | None:
    """True/False if a real connection attempt ran and succeeded/failed;
    None if it couldn't even be attempted (no `docker` on PATH here) --
    that's not treated as a failure, just "couldn't check". Runs a
    throwaway `postgres:17-alpine` container rather than requiring a
    Postgres client (or driver) installed on the bare host -- Docker is
    already the one hard requirement this whole project has."""
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "-e", "PGCONNECT_TIMEOUT=8", "postgres:17-alpine", "psql", url, "-c", "SELECT 1;"],
            timeout=30,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        print("(Connection attempt timed out.)")
        return False
    return result.returncode == 0


def _prompt_external_database() -> str:
    """Loops on a failed connection test rather than giving up outright
    -- a typo in the URL is the common case, and re-prompting the one
    field that's wrong is friendlier than aborting the whole run."""
    while True:
        url = _ask("External Postgres connection string (postgresql://user:password@host:5432/rain)")
        if not url:
            return url
        print("Testing the connection...")
        result = _test_postgres_connection(url)
        if result is True:
            print("Connected successfully.")
            return url
        if result is None:
            print("(Couldn't run a connection test -- `docker` isn't on PATH here. Continuing without one.)")
            return url
        if _ask_yes_no("Could not connect with that URL. Continue with it anyway?", default=False):
            return url
        # Otherwise loop back and ask for the URL again.


def _prompt_deployment_choices() -> dict[str, str]:
    print("\nA few questions to configure this deployment (Enter accepts the default).\n")

    if _ask_yes_no(
        "Use the default setup -- RAIN's own built-in Postgres container, local "
        "document storage, and a separate worker container?",
        default=True,
    ):
        return {}
    print()  # visual break before the more detailed questions below

    values: dict[str, str] = {}
    profiles = ["local-db", "web-frontend", "worker"]

    if not _ask_yes_no("Use RAIN's own built-in Postgres container?", default=True):
        values["POSTGRES_URL"] = _prompt_external_database()
        profiles.remove("local-db")
        # RAIN's own Postgres image always has pgvector baked in (see
        # db/Dockerfile), so this is only worth asking once an external
        # instance is in the picture -- and defaults to "no" there,
        # unlike every other question here: it's reserved for a future
        # semantic-search feature nothing uses yet, but a managed/
        # restricted Postgres refusing to create it (a permission error
        # on a typical minimum-privilege role, or the extension not
        # being offered at all -- standard RDS in AWS GovCloud, e.g.)
        # fails the whole migration chain outright, a far worse outcome
        # than just not getting an unused placeholder column.
        if not _ask_yes_no(
            "Does that Postgres support the pgvector extension? (reserved for a future "
            "semantic-search feature, unused today -- say no if you're not sure, or for "
            "most managed/restricted instances)",
            default=False,
        ):
            values["ENABLE_PGVECTOR"] = "false"

    if _ask_yes_no("Store documents in S3 (or an S3-compatible service) instead of local disk?", default=False):
        values["S3_BUCKET"] = _ask("S3 bucket name")
        values["S3_REGION"] = _ask("S3 region (blank is fine for a non-AWS endpoint)")
        values["S3_ENDPOINT_URL"] = _ask("S3 endpoint URL (blank for real AWS S3, set it for MinIO/etc.)")
        values["S3_ACCESS_KEY_ID"] = _ask("S3 access key ID (blank to use an IAM role instead of a static key)")
        if values["S3_ACCESS_KEY_ID"]:
            values["S3_SECRET_ACCESS_KEY"] = _ask("S3 secret access key")

    if _ask_yes_no(
        "Merge the worker (syslog listener, rule engine, notifications) into the app "
        "container instead of running it separately?",
        default=False,
    ):
        values["EMBED_WORKER"] = "true"
        profiles.remove("worker")

    if not _ask_yes_no(
        "Use Caddy as RAIN's reverse proxy (automatic HTTPS)? Say no if something else "
        "already terminates TLS in front of RAIN (e.g. an ALB, an existing reverse proxy).",
        default=True,
    ):
        # Keeps WEB_FRONTEND and COMPOSE_PROFILES in sync automatically --
        # .env.example documents these as needing to be hand-edited
        # together (Compose profiles can't be toggled from inside a plain
        # KEY=VALUE variable), but there's no reason this one script,
        # which is already writing both, can't just do that itself.
        values["WEB_FRONTEND"] = "false"
        profiles.remove("web-frontend")

    values["COMPOSE_PROFILES"] = ",".join(profiles)
    return values


def main() -> None:
    if ENV_PATH.exists():
        print(f".env already exists at {ENV_PATH}, leaving it untouched.")
        return

    if not EXAMPLE_PATH.exists():
        raise SystemExit(f"missing template: {EXAMPLE_PATH}")

    text = EXAMPLE_PATH.read_text(encoding="utf-8")
    text = text.replace("POSTGRES_PASSWORD=", f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}")
    text = text.replace("APP_SECRET_KEY=", f"APP_SECRET_KEY={secrets.token_urlsafe(48)}")

    if _interactive():
        for key, value in _prompt_deployment_choices().items():
            text = _set(text, key, value)
    else:
        print("Non-interactive session -- skipping deployment questions, using every default.")

    ENV_PATH.write_text(text, encoding="utf-8")
    print(f"\nWrote {ENV_PATH}.")
    print("Edit RAIN_DOMAIN in .env if you have a public DNS name for automatic ACME certs.")
    print("Next: docker compose up --build")


if __name__ == "__main__":
    main()
