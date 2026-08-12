"""Publishes newly-received syslog events to per-tenant Postgres NOTIFY
channels, so the live-viewer WebSocket (rain.modules.tickets.live) can
stream them without polling. Same LISTEN/NOTIFY approach as
rain.core.config_store, just per-tenant instead of instance-wide.

One shared connection publishes (cheap, reused across every event); each
connected live-viewer client opens its own LISTEN connection -- fine at
the connection counts this is built for. A heavier deployment would put a
proper pub/sub broker in front instead.
"""
from __future__ import annotations

import logging

import asyncpg

from rain.settings import get_settings

logger = logging.getLogger("rain.live_bus")


def channel_for(schema_name: str) -> str:
    return f"rain_syslog_{schema_name}"


def asyncpg_dsn() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class LiveEventBus:
    def __init__(self) -> None:
        self._conn: asyncpg.Connection | None = None

    async def start(self) -> None:
        self._conn = await asyncpg.connect(dsn=asyncpg_dsn())

    async def stop(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def publish(self, schema_name: str, payload: str) -> None:
        if self._conn is None:
            logger.warning("live event bus not started; dropping event for %s", schema_name)
            return
        try:
            await self._conn.execute("SELECT pg_notify($1, $2)", channel_for(schema_name), payload)
        except Exception:
            logger.exception("failed to publish live syslog event for %s", schema_name)


live_bus = LiveEventBus()
