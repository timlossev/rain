"""Programmatic Alembic driver for the two independent migration chains.

`backend/alembic.ini` has two named sections, `[control]` and `[tenant]`,
each pointing at its own script_location -- Alembic's documented recipe
for running multiple migration environments from one .ini file
(alembic.config.Config(..., ini_section=...)), used here so `alembic -n
control ...` / `alembic -n tenant ...` still work for local exploration
from the CLI (see README).

Programmatic use below does *not* rely on Config resolving script_location
out of that ini section, though: `ini_section` interacting with newer
Alembic's ini/TOML config resolution turned out to be version-sensitive
enough (a `command.upgrade()` with a correctly-populated `[control]`
section raised "No 'script_location' key found in configuration" against
the version this pulled in) that it wasn't worth pinning down further --
`script_location` is set explicitly in Python instead, which every
Alembic version reading this respects unambiguously.

Alembic's `command.upgrade` is synchronous and blocks on its own
`asyncio.run(...)` inside each env.py, so it must never be called directly
from within a running event loop -- always go through the `*_async` helpers
below, which hop onto a worker thread via `asyncio.to_thread`.

Locating alembic.ini / migrations/: `Path(__file__)`-relative navigation
(e.g. `parents[3]`) does *not* work here -- it assumes the source-tree
layout (`backend/src/rain/db/migrate.py` -> `backend/`), which only holds
when running from an editable checkout. A real `pip install .` (what the
Docker image does) copies this module into `site-packages`, so at runtime
`__file__` is something like `/venv/lib/python3.12/site-packages/rain/
db/migrate.py` and the same parent-walk lands on `/venv/lib/python3.12`
instead. What's actually reliable is the process's current working
directory: the Docker image's WORKDIR is `/app`, which is exactly where
the Dockerfile COPYs alembic.ini and migrations/ (siblings of the
installed package, not part of it); local dev/CI is documented (README)
to run from `backend/`, the same relationship. So both of this project's
two real invocation contexts already guarantee cwd == the directory
holding these files -- that's what's used below, with an explicit check
so a wrong invocation directory fails with a clear message instead of a
confusing Alembic internal error.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from rain.settings import get_settings

APP_ROOT = Path.cwd()
ALEMBIC_INI = APP_ROOT / "alembic.ini"
MIGRATIONS_DIR = APP_ROOT / "migrations"


def _config(section: str) -> Config:
    # Checked lazily (not at import time) so merely importing this module
    # -- which rain.main does at startup -- doesn't fail scripts/tests that
    # import it without ever actually running a migration.
    if not ALEMBIC_INI.exists():
        raise RuntimeError(
            f"expected {ALEMBIC_INI} to exist -- rain must be run with its working "
            f"directory set to the 'backend' project root (Docker: WORKDIR /app; "
            f"local dev: cd backend first), not {APP_ROOT}"
        )
    cfg = Config(str(ALEMBIC_INI), ini_section=section)
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR / section))
    return cfg


def upgrade_control(revision: str = "head") -> None:
    command.upgrade(_config("control"), revision)


def upgrade_tenant(schema: str, revision: str = "head") -> None:
    cfg = _config("tenant")
    cfg.attributes["schema"] = schema
    command.upgrade(cfg, revision)


async def upgrade_control_async() -> None:
    await asyncio.to_thread(upgrade_control)


async def upgrade_tenant_async(schema: str) -> None:
    await asyncio.to_thread(upgrade_tenant, schema)
