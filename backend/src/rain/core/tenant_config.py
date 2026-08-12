"""Per-tenant runtime settings (rain.db.tenant_models.TenantConfig).

Unlike control.global_config (rain.core.config_store), this doesn't need a
process-wide cache with LISTEN/NOTIFY invalidation: every read already goes
through a tenant-scoped session resolved per request, so it's just a cheap
single-row lookup on the connection the request already has open.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import TenantConfig

DEFAULTS: dict[str, Any] = {
    "event_retention_days": 14,
}


async def get_tenant_config(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.get(TenantConfig, key)
    if row is not None:
        return row.value
    return default if default is not None else DEFAULTS.get(key)


async def set_tenant_config(db: AsyncSession, key: str, value: Any, *, updated_by: int | None = None) -> None:
    row = await db.get(TenantConfig, key)
    if row is None:
        db.add(TenantConfig(key=key, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by
    await db.commit()
