from __future__ import annotations

from rain.core.nav_registry import NavNode, nav_registry

nav_registry.register(
    NavNode(
        key="documents",
        label="Documents",
        icon="file",
        href="/documents",
        order=30,  # after Tickets (10) and Assets (20)
        children=[
            NavNode(key="documents-all", label="All Documents", href="/documents", order=1),
            NavNode(key="documents-upload", label="Upload", href="/documents/new", order=2),
        ],
    )
)
