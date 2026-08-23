from __future__ import annotations

from functools import partial

from sqlalchemy import func, select

from rain.core.nav_registry import NavNode, nav_registry
from rain.core.tenancy import RequestContext
from rain.db.base import tenant_session
from rain.db.tenant_models import ServiceCatalogItem, SyslogEvent, Ticket, TicketStatus


async def _event_count(ctx: RequestContext) -> int | None:
    if ctx.active_tenant is None:
        return None
    async with tenant_session(ctx.active_tenant.schema_name) as db:
        return await db.scalar(select(func.count(SyslogEvent.id)))


async def _active_catalog_item_count(ctx: RequestContext) -> int | None:
    if ctx.active_tenant is None:
        return None
    async with tenant_session(ctx.active_tenant.schema_name) as db:
        return await db.scalar(select(func.count(ServiceCatalogItem.id)).where(ServiceCatalogItem.is_active.is_(True)))


async def _active_ticket_count(ctx: RequestContext, *, ticket_type: str) -> int | None:
    """Active = not sitting on a status flagged is_closed (tenant-
    configured, not a hardcoded "closed" string -- same definition the
    ticket detail page's status stepper uses)."""
    if ctx.active_tenant is None:
        return None
    async with tenant_session(ctx.active_tenant.schema_name) as db:
        closed_keys = select(TicketStatus.key).where(TicketStatus.is_closed.is_(True))
        return await db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.ticket_type == ticket_type, Ticket.status.not_in(closed_keys)
            )
        )


nav_registry.register(
    NavNode(
        key="tickets",
        label="Records Authority",
        icon="ticket",
        href="/tickets",
        order=10,  # ahead of Assets -- ticketing is the primary focus of RAIN
        children=[
            NavNode(key="tickets-live", label="Events", href="/tickets/live", order=1, count_provider=_event_count),
            NavNode(
                key="tickets-incidents",
                label="Incidents",
                href="/tickets?ticket_type=incident",
                order=2,
                count_provider=partial(_active_ticket_count, ticket_type="incident"),
            ),
            NavNode(
                key="tickets-vulns",
                label="Vulnerabilities",
                href="/tickets?ticket_type=vulnerability",
                order=3,
                count_provider=partial(_active_ticket_count, ticket_type="vulnerability"),
            ),
            NavNode(
                key="tickets-changes",
                label="Changes",
                href="/tickets?ticket_type=change",
                order=4,
                count_provider=partial(_active_ticket_count, ticket_type="change"),
            ),
            # rain.modules.catalog: a self-service form that produces a
            # ticket on submission -- lives under Records Authority rather
            # than standing alone, same reason Export does, since it's
            # just another way of producing one of these.
            NavNode(
                key="tickets-catalog",
                label="Service Catalog",
                href="/catalog",
                order=5,
                count_provider=_active_catalog_item_count,
            ),
            NavNode(key="tickets-fields", label="Custom Fields", href="/tickets/fields", order=6),
            NavNode(key="tickets-export", label="Export", href="/tickets/export/run", order=7),
            NavNode(key="tickets-import", label="Import", href="/tickets/import", order=8),
        ],
    )
)
