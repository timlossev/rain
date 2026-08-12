from __future__ import annotations

from rain.core.nav_registry import NavNode, nav_registry

nav_registry.register(
    NavNode(
        key="tickets",
        label="Tickets",
        icon="ticket",
        href="/tickets",
        order=10,  # ahead of Assets -- ticketing is the primary focus of RAIN
        children=[
            NavNode(key="tickets-live", label="Events", href="/tickets/live", order=1),
            NavNode(key="tickets-incidents", label="Incidents", href="/tickets?ticket_type=incident", order=2),
            NavNode(key="tickets-vulns", label="Vulnerabilities", href="/tickets?ticket_type=vulnerability", order=3),
            NavNode(key="tickets-rules", label="Event Policies", href="/tickets/rules/all", order=4),
            NavNode(key="tickets-platform-events", label="Platform Events", href="/tickets/platform-events", order=5),
            NavNode(key="tickets-export", label="Export", href="/tickets/export/run", order=6),
        ],
    )
)
