"""Entrypoints installed as console scripts (see pyproject.toml
[project.scripts]) -- `rain-web` and `rain-worker` are the two commands the
`app` and `worker` containers run (same image, different command)."""
from __future__ import annotations

import asyncio
import logging

import uvicorn

from rain.core.config_store import config_store
from rain.db import migrate, provisioning
from rain.db.base import dispose_engine

logger = logging.getLogger("rain.cli")


def run_web() -> None:
    uvicorn.run("rain.main:app", host="0.0.0.0", port=8000, log_level="info", ws="wsproto")


async def _worker_main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Defensive: bring the DB up to date even if the app container hasn't
    # started yet -- both processes run the same idempotent migration step.
    await migrate.upgrade_control_async()
    await provisioning.reconcile_all_tenant_schemas()
    await config_store.load_all()
    await config_store.start_listener()
    logger.info("rain-worker up (Milestone 1 placeholder -- becomes the syslog listener / rule engine / notifier in Milestone 2)")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await config_store.stop_listener()
        await dispose_engine()


def run_worker() -> None:
    try:
        asyncio.run(_worker_main())
    except KeyboardInterrupt:
        pass
