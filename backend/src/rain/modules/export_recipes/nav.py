from __future__ import annotations

from sqlalchemy import func, select

from rain.core.nav_registry import NavNode, nav_registry
from rain.core.tenancy import RequestContext
from rain.db.base import tenant_session
from rain.db.tenant_models import ExportRecipe


async def _recipe_count(ctx: RequestContext) -> int | None:
    if ctx.active_tenant is None:
        return None
    async with tenant_session(ctx.active_tenant.schema_name) as db:
        return await db.scalar(select(func.count(ExportRecipe.id)))


nav_registry.register(
    NavNode(
        key="export-recipes",
        label="Export Recipes",
        icon="repeat",
        href="/export-recipes",
        order=35,  # after Documents (30), ahead of Admin (90)
        count_provider=_recipe_count,
    )
)
