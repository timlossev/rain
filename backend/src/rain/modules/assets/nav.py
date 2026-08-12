from __future__ import annotations

from sqlalchemy import select

from rain.core.nav_registry import NavNode, nav_registry
from rain.core.tenancy import RequestContext
from rain.db.base import tenant_session
from rain.db.tenant_models import AssetType


async def _asset_type_children(ctx: RequestContext) -> list[NavNode]:
    if ctx.active_tenant is None:
        return []
    async with tenant_session(ctx.active_tenant.schema_name) as db:
        result = await db.execute(
            select(AssetType).where(AssetType.is_active.is_(True)).order_by(AssetType.sort_order, AssetType.name)
        )
        types = list(result.scalars())
    return [
        NavNode(key=f"assets-type-{t.id}", label=t.name, href=f"/assets?asset_type_id={t.id}", order=i)
        for i, t in enumerate(types)
    ]


nav_registry.register(
    NavNode(
        key="assets",
        label="Assets",
        icon="server",
        href="/assets",
        order=20,
        children=[
            NavNode(key="assets-all", label="All Assets", href="/assets", order=1),
            NavNode(key="assets-by-type", label="By Type", order=2, children_provider=_asset_type_children),
            NavNode(key="assets-types", label="Asset Types", href="/assets/types", order=3),
            NavNode(key="assets-fields", label="Custom Fields", href="/assets/fields", order=4),
            NavNode(key="assets-export", label="Export", href="/assets/export", order=5),
            NavNode(key="assets-import", label="Import", href="/assets/import", order=6),
            NavNode(key="assets-sync", label="Cloud Sync", href="/assets/sync", order=7),
        ],
    )
)
