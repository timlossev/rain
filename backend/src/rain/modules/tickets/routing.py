"""Resolves which tenant an incoming syslog event belongs to, before it can
be written into any tenant schema -- this has to run against the control
schema since the tenant isn't known yet at this point."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.control_models import SyslogSourceMap, Tenant


async def resolve_tenant_for_event(control_db: AsyncSession, *, host: str | None, program: str | None) -> Tenant | None:
    result = await control_db.execute(
        select(SyslogSourceMap, Tenant)
        .join(Tenant, SyslogSourceMap.tenant_id == Tenant.id)
        .where(SyslogSourceMap.is_active.is_(True), Tenant.is_active.is_(True))
        .order_by(SyslogSourceMap.sort_order)
    )
    for source_map, tenant in result.all():
        value = host if source_map.match_field == "host" else program
        if value is None:
            continue
        try:
            matched = re.search(source_map.pattern, value) if source_map.is_regex else value == source_map.pattern
        except re.error:
            continue
        if matched:
            return tenant
    return None
