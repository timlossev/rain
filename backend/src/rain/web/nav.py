from __future__ import annotations

from rain.core.nav_registry import nav_registry
from rain.core.tenancy import RequestContext
from rain.core.tenant_config import get_tenant_config
from rain.db.base import tenant_session


async def build_nav_context(ctx: RequestContext) -> dict:
    return {
        "nav_tree": await nav_registry.tree_for(ctx),
        "app_custom_js": await _app_custom_js(ctx),
    }


async def _app_custom_js(ctx: RequestContext) -> str:
    """The active tenant's custom-JS snippet for the authenticated app
    shell (Admin > Branding > "Tenant defaults"), rendered by base.html
    only inside its `{% if ctx %}` branch -- i.e. only on pages that call
    build_nav_context at all, which the client portal and login/setup
    screens never do (see rain.modules.portal's own portal_custom_js,
    threaded through separately for exactly that reason: the two are
    deliberately not the same flag). Called on every authenticated page
    load (build_nav_context already is), so this stays a single cheap
    tenant_config lookup rather than anything heavier -- empty string
    with no active tenant, same as every other tenant-scoped default in
    this app."""
    if ctx.active_tenant is None:
        return ""
    async with tenant_session(ctx.active_tenant.schema_name) as tenant_db:
        return await get_tenant_config(tenant_db, "app_custom_js")
