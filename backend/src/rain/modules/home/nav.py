from __future__ import annotations

from rain.core.nav_registry import NavNode, nav_registry

nav_registry.register(
    NavNode(
        key="home",
        label="Home",
        icon="home",
        href="/home",
        order=5,  # ahead of Records Authority (10) -- the landing page comes first
    )
)
