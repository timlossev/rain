from __future__ import annotations

from rain.core.nav_registry import NavNode, nav_registry

nav_registry.register(
    NavNode(
        key="tickets",
        label="Records Authority",
        icon="ticket",
        href="/tickets",
        order=10,  # ahead of Assets -- ticketing is the primary focus of RAIN
        children=[
            NavNode(key="tickets-live", label="Events", href="/tickets/live", order=1),
            NavNode(key="tickets-incidents", label="Incidents", href="/tickets?ticket_type=incident", order=2),
            NavNode(key="tickets-vulns", label="Vulnerabilities", href="/tickets?ticket_type=vulnerability", order=3),
            NavNode(key="tickets-changes", label="Changes", href="/tickets?ticket_type=change", order=4),
            NavNode(key="tickets-export", label="Export", href="/tickets/export/run", order=5),
        ],
    )
)
