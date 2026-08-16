"""The syslog listener + background loops (retention sweep, calendar sweep,
LDAP sync) as a start()/stop() pair, independent of whichever process
already brought the DB up to date and loaded config before calling it.
Two callers:

- rain.cli._worker_main: the standalone `rain-worker` process, after its
  own migrate/config_store setup, blocking on this until shutdown.
- rain.main's lifespan, when Settings.embed_worker is true: folds these
  same services into the `app` process instead of a separate `worker`
  container -- see docker-compose.yml's "minimal mode" comment. uvicorn's
  own event loop is what keeps the process (and these background tasks)
  alive here, not a blocking serve_forever() call the way the standalone
  worker process needs one -- an asyncio server/datagram endpoint is
  already accepting connections as soon as it's created, no separate
  "now actually serve" step required.
"""
from __future__ import annotations

import asyncio
import logging

from rain.settings import get_settings

logger = logging.getLogger("rain.worker_runtime")


class WorkerServices:
    def __init__(self) -> None:
        self._tcp_server = None
        self._udp_transport = None
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        # Imported locally, not at module load time: these pull in the
        # tenant model/service layer, which this module is deliberately
        # kept independent of so importing it (e.g. from rain.main, at
        # the top of the file, before settings are even read) can't
        # accidentally widen rain.main's own import surface just to
        # reach Settings.embed_worker's off-by-default case.
        from rain.modules.auth.ldap_sync import ldap_sync_loop
        from rain.modules.calendar.sweep import calendar_sweep_loop
        from rain.modules.tickets.listener import retention_loop, start_listener
        from rain.modules.tickets.live_bus import live_bus

        await live_bus.start()
        settings = get_settings()
        self._tcp_server, self._udp_transport = await start_listener(port=settings.syslog_port)
        self._tasks = [
            asyncio.create_task(retention_loop()),
            asyncio.create_task(calendar_sweep_loop()),
            asyncio.create_task(ldap_sync_loop()),
        ]
        logger.info("worker services up: syslog listener + rule engine + notifications + calendar sweep + LDAP sync")

    async def stop(self) -> None:
        from rain.modules.tickets.live_bus import live_bus

        for task in self._tasks:
            task.cancel()
        self._tasks = []
        if self._udp_transport is not None:
            self._udp_transport.close()
            self._udp_transport = None
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
            self._tcp_server = None
        await live_bus.stop()
