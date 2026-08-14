"""ServiceNow-style tree navigation, built from a registry modules add to at
import time -- the extension point future modules (Ticketing, Documents,
...) plug into without touching the base layout.

The tree is computed fresh per request (dynamic children, e.g. Assets'
"By Type" list, are cheap to query at this scale) and rendered with plain
Alpine.js for client-side expand/collapse -- no round trip needed just to
open a branch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable, Sequence

if TYPE_CHECKING:
    from rain.core.tenancy import RequestContext

ChildrenProvider = Callable[["RequestContext"], Awaitable[Sequence["NavNode"]]]
CountProvider = Callable[["RequestContext"], Awaitable["int | None"]]


@dataclass
class NavNode:
    key: str
    label: str
    href: str | None = None
    icon: str | None = None
    order: int = 100
    roles: tuple[str, ...] = ("internal_admin", "client", "client_admin")
    children_provider: ChildrenProvider | None = None
    children: list["NavNode"] = field(default_factory=list)
    # A small live count shown as a badge next to the label (e.g. "12" on
    # Incidents) -- count_provider is the live/per-request version (a
    # tenant-scoped query), same shape as children_provider; `count`
    # itself is only ever the *resolved* value on a tree handed to a
    # template (see _resolve below), never set directly at registration.
    count: int | None = None
    count_provider: CountProvider | None = None


class NavRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, NavNode] = {}

    def register(self, node: NavNode) -> None:
        self._nodes[node.key] = node

    async def _resolve(self, node: NavNode, ctx: "RequestContext") -> NavNode:
        children = [c for c in node.children if ctx.user.role_key in c.roles]
        if node.children_provider is not None:
            children = children + [c for c in await node.children_provider(ctx) if ctx.user.role_key in c.roles]
        resolved_children = [await self._resolve(c, ctx) for c in sorted(children, key=lambda n: n.order)]
        count = await node.count_provider(ctx) if node.count_provider is not None else node.count
        return NavNode(
            key=node.key,
            label=node.label,
            href=node.href,
            icon=node.icon,
            order=node.order,
            roles=node.roles,
            children=resolved_children,
            count=count,
        )

    async def tree_for(self, ctx: "RequestContext") -> list[NavNode]:
        visible = sorted(
            (n for n in self._nodes.values() if ctx.user.role_key in n.roles),
            key=lambda n: n.order,
        )
        return [await self._resolve(n, ctx) for n in visible]


nav_registry = NavRegistry()
