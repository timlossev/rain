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
    uvicorn.run("rain.main:app", host="0.0.0.0", port=8000, log_level="info", ws="wsproto")


async def _worker_main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Defensive: bring the DB up to date even if the app container hasn't
    # started yet -- both processes run the same idempotent migration step.
    await migrate.upgrade_control_async()
    await provisioning.reconcile_all_tenant_schemas()
    await config_store.load_all()
    await config_store.start_listener()

    from rain.modules.tickets.listener import retention_loop, start_listener
    from rain.modules.tickets.live_bus import live_bus

    await live_bus.start()
    settings = get_settings()
    tcp_server, udp_transport = await start_listener(port=settings.syslog_port)
    retention_task = asyncio.create_task(retention_loop())

    logger.info("rain-worker up: syslog listener + rule engine + notifications")
    try:
        async with tcp_server:
            await tcp_server.serve_forever()
    finally:
        retention_task.cancel()
        udp_transport.close()
        await live_bus.stop()
        await config_store.stop_listener()
        await dispose_engine()


def run_worker() -> None:
    try:
        asyncio.run(_worker_main())
    except KeyboardInterrupt:
        pass
