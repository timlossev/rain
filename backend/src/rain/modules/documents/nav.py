from __future__ import annotations

from sqlalchemy import func, select

from rain.core.nav_registry import NavNode, nav_registry
from rain.core.tenancy import RequestContext
from rain.db.base import tenant_session
from rain.db.tenant_models import Document


async def _document_count(ctx: RequestContext) -> int | None:
    if ctx.active_tenant is None:
        return None
    async with tenant_session(ctx.active_tenant.schema_name) as db:
        return await db.scalar(select(func.count(Document.id)))


nav_registry.register(
    NavNode(
        key="documents",
        label="Documents",
        icon="file",
        href="/documents",
        order=30,  # after Tickets (10) and Assets (20)
        count_provider=_document_count,
        children=[
            NavNode(key="documents-all", label="All Documents", href="/documents", order=1),
            NavNode(key="documents-kanban", label="Kanban", href="/documents/kanban", order=2),
            NavNode(key="documents-upload", label="Upload", href="/documents/new", order=3),
        ],
    )
)
