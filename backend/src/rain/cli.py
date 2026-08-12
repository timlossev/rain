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
from rain.settings import get_settings

logger = logging.getLogger("rain.cli")


def run_web() -> None:
    # log_config=None: skip uvicorn's own logging.config.dictConfig() call
    # entirely and leave logging up to rain.main's logging.basicConfig().
    # The actual bug that made this app's logging go silent turned out to
    # be elsewhere -- migrations/*/env.py's fileConfig() call defaults to
    # disable_existing_loggers=True and was permanently disabling every
    # "rain.*" logger the moment the first migration ran at startup (fixed
    # there, with disable_existing_loggers=False) -- but dictConfig has
    # the exact same default-True footgun, so this stays as defense in
    # depth against the same class of bug recurring from uvicorn's side.
    uvicorn.run("rain.main:app", host="0.0.0.0", port=8000, log_level="info", ws="wsproto", log_config=None)


async def _worker_main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Defensive: bring the DB up to date even if the app container hasn't
    # started yet -- both processes run the same idempotent migration step.
    await migrate.upgrade_control_async()
    await provisioning.reconcile_all_tenant_schemas()
    await config_store.load_all()
    await config_store.start_listener()

    from rain.modules.calendar.sweep import calendar_sweep_loop
    from rain.modules.tickets.listener import retention_loop, start_listener
    from rain.modules.tickets.live_bus import live_bus

    await live_bus.start()
    settings = get_settings()
    tcp_server, udp_transport = await start_listener(port=settings.syslog_port)
    retention_task = asyncio.create_task(retention_loop())
    calendar_task = asyncio.create_task(calendar_sweep_loop())

    logger.info("rain-worker up: syslog listener + rule engine + notifications + calendar sweep")
    try:
        async with tcp_server:
            await tcp_server.serve_forever()
    finally:
        retention_task.cancel()
        calendar_task.cancel()
        udp_transport.close()
        await live_bus.stop()
        await config_store.stop_listener()
        await dispose_engine()


def run_worker() -> None:
    try:
        asyncio.run(_worker_main())
    except KeyboardInterrupt:
        pass
