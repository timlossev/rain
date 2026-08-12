from __future__ import annotations

from rain.core.nav_registry import NavNode, nav_registry

nav_registry.register(
    NavNode(
        key="calendar",
        label="Calendar",
        icon="calendar",
        href="/calendar",
        order=15,  # after Tickets, ahead of Assets
        children=[
            NavNode(key="calendar-view", label="Month View", href="/calendar", order=1),
            NavNode(key="calendar-new", label="New Entry", href="/calendar/new", order=2),
            NavNode(key="calendar-export", label="Export (.ics)", href="/calendar/export", order=3),
            NavNode(key="calendar-import", label="Import (.ics)", href="/calendar/import", order=4),
        ],
    )
)
