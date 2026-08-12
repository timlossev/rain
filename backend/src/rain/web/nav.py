from __future__ import annotations

from rain.core.nav_registry import nav_registry
from rain.core.tenancy import RequestContext


async def build_nav_context(ctx: RequestContext) -> dict:
    return {"nav_tree": await nav_registry.tree_for(ctx)}
