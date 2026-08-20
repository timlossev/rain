"""Resolves which tenant an incoming syslog event belongs to, before it can
be written into any tenant schema -- this has to run against the control
schema since the tenant isn't known yet at this point."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.control_models import SyslogSourceMap, Tenant


@dataclass(frozen=True)
class RoutingResult:
    """`tenant is None` still covers two different outcomes the caller
    (listener.py) both end up dropping the event for, but now
    distinguishably: `discarded` (a "discard" rule matched -- see
    SyslogSourceMap's action column -- meaning some admin deliberately
    asked for this source to go quiet) versus neither (nothing in
    syslog_source_map matched at all, which usually just means no rule
    -- not even a catch-all -- has been set up for this host/program
    yet). The caller logs the latter, not the former: a discard rule
    working as intended shouldn't warn on every matching event, but an
    event nothing was configured to route is exactly the kind of gap an
    admin needs to see, not one that silently vanishes."""

    tenant: Tenant | None
    discarded: bool = False


async def resolve_tenant_for_event(
    control_db: AsyncSession, *, host: str | None, program: str | None, message: str | None = None
) -> RoutingResult:
    """A LEFT JOIN (not the inner join this used to be) so discard rules,
    which have no tenant_id, are still fetched and take part in the
    sort_order race.

    Ties within the same sort_order break discard-before-route rather
    than by insertion order (Postgres doesn't even guarantee that without
    an explicit tie-breaker) -- a fresh discard rule (tickets/live's
    "Discard these", or one added by hand) is otherwise silently
    shadowed by an existing catch-all route rule (pattern ".*") at the
    same default sort_order of 0, which is exactly the setup admins are
    most likely to already have."""
    result = await control_db.execute(
        select(SyslogSourceMap, Tenant)
        .outerjoin(Tenant, SyslogSourceMap.tenant_id == Tenant.id)
        .where(SyslogSourceMap.is_active.is_(True))
        .order_by(SyslogSourceMap.sort_order, case((SyslogSourceMap.action == "discard", 0), else_=1))
    )
    for source_map, tenant in result.all():
        if source_map.action == "route" and (tenant is None or not tenant.is_active):
            continue
        value = {"host": host, "program": program, "message": message}.get(source_map.match_field, host)
        if value is None:
            continue
        try:
            matched = re.search(source_map.pattern, value) if source_map.is_regex else value == source_map.pattern
        except re.error:
            continue
        if matched:
            if source_map.action == "discard":
                return RoutingResult(tenant=None, discarded=True)
            return RoutingResult(tenant=tenant)
    return RoutingResult(tenant=None)
