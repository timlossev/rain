#!/usr/bin/env python3
"""Generate a .env with strong random secrets on first run.

Run this once before `docker compose up`. If a .env already exists it is
left untouched (so restarts/upgrades keep working with the same secrets).
This is the *only* manual step RAIN requires -- every other setting is
configured at runtime through the in-app setup wizard and Admin UI, stored
in Postgres.
"""
from __future__ import annotations

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"


def main() -> None:
    if ENV_PATH.exists():
        print(f".env already exists at {ENV_PATH}, leaving it untouched.")
        return

    if not EXAMPLE_PATH.exists():
        raise SystemExit(f"missing template: {EXAMPLE_PATH}")

    text = EXAMPLE_PATH.read_text(encoding="utf-8")
    text = text.replace("POSTGRES_PASSWORD=", f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}")
    text = text.replace("APP_SECRET_KEY=", f"APP_SECRET_KEY={secrets.token_urlsafe(48)}")

    ENV_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {ENV_PATH} with freshly generated secrets.")
    print("Edit RAIN_DOMAIN in .env if you have a public DNS name for automatic ACME certs.")
    print("Next: docker compose up --build")


if __name__ == "__main__":
    main()
