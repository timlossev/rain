"""Per-tenant runtime settings (rain.db.tenant_models.TenantConfig).

Unlike control.global_config (rain.core.config_store), this doesn't need a
process-wide cache with LISTEN/NOTIFY invalidation: every read already goes
through a tenant-scoped session resolved per request, so it's just a cheap
single-row lookup on the connection the request already has open.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.pagination import DEFAULT_PAGE_SIZE
from rain.db.tenant_models import TenantConfig

DEFAULTS: dict[str, Any] = {
    # How long a syslog event that never got promoted into a ticket
    # ("untreated") stays around before rain.modules.tickets.listener.
    # run_retention_sweep deletes it. Hours (not days) so a short window
    # like the 12h default is expressible exactly, not rounded to a
    # whole day.
    "event_retention_hours": 12,
    # rain.modules.portal (the public "/portal/<slug>" incident intake
    # page). Both default to the locked-down choice -- an admin opts a
    # tenant *into* anonymous access and *into* dropping instance
    # branding, not the other way around.
    "portal_require_auth": True,
    "portal_branded": True,
    # rain.modules.portal's "Shareable documents" tab -- reachable by
    # every visitor (even anonymous, even with portal_require_auth on)
    # whenever the tenant has at least one Document.is_shareable row. Free
    # text so an admin can rename it to e.g. "Trust Center" on Admin >
    # Branding; the tab itself only appears once a shareable document
    # exists, so there's no separate on/off flag to go with this one.
    "portal_shareable_documents_label": "Shareable documents",
    # rain.modules.tickets.rootcause.analyze: off by default -- a comment
    # on every single closed ticket is noise for a tenant that never asked
    # for it. An admin opts in under Tickets > Platform Response Rules
    # (it's a reaction to a ticket event, closure, same as every rule on
    # that screen -- not a property of the statuses themselves); the
    # on-demand "Analyze root cause" button on a ticket works regardless
    # of this flag.
    "auto_root_cause_on_close": False,
    # rain.core.pagination.paginate's own page_size, tenant-overridable
    # (Admin > Branding > "Tenant defaults") for every tenant-scoped
    # record list in the app (Tickets, Assets, Documents, and every
    # admin config list under this tenant) -- NOT applied to the handful
    # of platform-level lists (Admin > Tenants, platform Users, Syslog
    # Sources) that read from `control` via control_session() rather
    # than a tenant schema, since those aren't any one tenant's records
    # to have an opinion on the page size of.
    "default_page_size": DEFAULT_PAGE_SIZE,
}

# Distinguishes "caller passed no default" from "caller explicitly passed
# a falsy default" (False, 0, "") -- `default: Any = None` couldn't tell
# those apart, so get_tenant_config(db, key, False) would silently ignore
# the False and fall through to DEFAULTS.get(key) instead. Not hit by any
# caller before portal_require_auth/portal_branded (the first booleans
# this module handled), which is exactly the type of value that's often
# legitimately False.
_UNSET = object()


async def get_tenant_config(db: AsyncSession, key: str, default: Any = _UNSET) -> Any:
    row = await db.get(TenantConfig, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key) if default is _UNSET else default


async def get_tenant_configs(db: AsyncSession, keys: list[str]) -> dict[str, Any]:
    """Bulk get_tenant_config -- one query for several keys instead of one
    round trip each. rain.modules.portal reads its two portal_* flags
    together on every page load (including the public, unauthenticated-
    reachable one), and Admin > Branding does the same for the active
    tenant. A key with no stored row falls back to DEFAULTS, same as the
    single-key version."""
    if not keys:
        return {}
    result = await db.execute(select(TenantConfig).where(TenantConfig.key.in_(keys)))
    stored = {row.key: row.value for row in result.scalars()}
    return {key: stored[key] if key in stored else DEFAULTS.get(key) for key in keys}


async def set_tenant_config(db: AsyncSession, key: str, value: Any, *, updated_by: int | None = None) -> None:
    await set_tenant_configs(db, {key: value}, updated_by=updated_by)


async def set_tenant_configs(db: AsyncSession, values: dict[str, Any], *, updated_by: int | None = None) -> None:
    """Bulk set_tenant_config -- upserts every key in one commit instead
    of one commit per key, so a form that saves more than one setting at
    once (e.g. the portal's two flags on Admin > Branding) can't be left
    half-applied by a failure between two separate commits."""
    for key, value in values.items():
        row = await db.get(TenantConfig, key)
        if row is None:
            db.add(TenantConfig(key=key, value=value, updated_by=updated_by))
        else:
            row.value = value
            row.updated_by = updated_by
    await db.commit()
