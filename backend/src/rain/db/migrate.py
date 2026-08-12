"""Programmatic Alembic driver for the two independent migration chains.

`backend/alembic.ini` has two named sections, `[control]` and `[tenant]`,
each pointing at its own script_location. This is Alembic's documented
recipe for running multiple migration environments from one .ini file
(alembic.config.Config(..., ini_section=...)).

Alembic's `command.upgrade` is synchronous and blocks on its own
`asyncio.run(...)` inside each env.py, so it must never be called directly
from within a running event loop -- always go through the `*_async` helpers
below, which hop onto a worker thread via `asyncio.to_thread`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from rain.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[3]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def _config(section: str) -> Config:
    cfg = Config(str(ALEMBIC_INI), ini_section=section)
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
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
