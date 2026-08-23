"""In-process cache over control.global_config, the table that holds every
piece of instance-wide runtime configuration (instance name, branding,
...). Kept fresh across the app and worker processes via Postgres
LISTEN/NOTIFY -- no Redis needed just for this.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg
from sqlalchemy import select

from rain.db.base import control_session
from rain.db.control_models import GlobalConfig
from rain.settings import get_settings

logger = logging.getLogger("rain.config_store")

NOTIFY_CHANNEL = "rain_global_config_changed"

# Curated, dependency-free font stacks (system/web-safe fonts only -- no
# Google Fonts/CDN download, consistent with the rest of the app). The
# admin branding picker offers exactly these; the CSS value itself is what
# gets stored in global_config and injected into base.html's <style> block.
FONT_CHOICES: list[tuple[str, str]] = [
    ("System UI (default)", '"Segoe UI", -apple-system, BlinkMacSystemFont, Inter, Roboto, sans-serif'),
    ("Classic (Arial)", "Arial, Helvetica, sans-serif"),
    ("Humanist (Verdana)", "Verdana, Geneva, sans-serif"),
    ("Friendly (Trebuchet MS)", '"Trebuchet MS", Tahoma, sans-serif'),
    ("Serif (Georgia)", 'Georgia, "Times New Roman", serif'),
    ("Serif (Times New Roman)", '"Times New Roman", Times, serif'),
    ("Monospace (Consolas)", 'Consolas, "Cascadia Mono", "SF Mono", monospace'),
]
DEFAULT_FONT_FAMILY = FONT_CHOICES[0][1]

# Defaults used until the setup wizard writes real values.
DEFAULTS: dict[str, Any] = {
    "instance_name": "RAIN",
    "accent_color": "#3d6b73",
    "logo_path": None,
    "portal_background_path": None,
    "font_family": DEFAULT_FONT_FAMILY,
    "setup_complete": False,
}


def _to_asyncpg_dsn(sqlalchemy_url: str) -> str:
    # asyncpg.connect() wants a plain "postgresql://" DSN, not SQLAlchemy's
    # driver-qualified "postgresql+asyncpg://" form.
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class ConfigStore:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._listener_conn: asyncpg.Connection | None = None

    async def load_all(self) -> None:
        async with control_session() as session:
            result = await session.execute(select(GlobalConfig))
            self._cache = {row.key: row.value for row in result.scalars()}

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._cache:
            return self._cache[key]
        if default is not None:
            return default
        return DEFAULTS.get(key)

    def as_dict(self) -> dict[str, Any]:
        merged = dict(DEFAULTS)
        merged.update(self._cache)
        return merged

    async def set(self, key: str, value: Any, *, updated_by: int | None = None) -> None:
        async with control_session() as session:
            row = await session.get(GlobalConfig, key)
            if row is None:
                row = GlobalConfig(key=key, value=value, updated_by=updated_by)
                session.add(row)
            else:
                row.value = value
                row.updated_by = updated_by
            await session.commit()
        self._cache[key] = value
        await self._notify(key)

    async def _notify(self, key: str) -> None:
        try:
            conn = await asyncpg.connect(dsn=_to_asyncpg_dsn(get_settings().database_url))
            try:
                await conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, key)
            finally:
                await conn.close()
        except Exception:
            logger.exception("failed to publish global_config change notification for key=%s", key)

    async def start_listener(self) -> None:
        dsn = _to_asyncpg_dsn(get_settings().database_url)
        self._listener_conn = await asyncpg.connect(dsn=dsn)

        async def _on_notify(_conn: Any, _pid: int, _channel: str, payload: str) -> None:
            await self._reload_key(payload)

        await self._listener_conn.add_listener(NOTIFY_CHANNEL, _on_notify)

    async def stop_listener(self) -> None:
        if self._listener_conn is not None:
            await self._listener_conn.close()
            self._listener_conn = None

    async def _reload_key(self, key: str) -> None:
        async with control_session() as session:
            row = await session.get(GlobalConfig, key)
            self._cache[key] = row.value if row is not None else None


config_store = ConfigStore()
