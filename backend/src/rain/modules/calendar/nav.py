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
            # Export/Import aren't destinations in their own right the way
            # Month View/New Entry are -- reachable as buttons on /calendar
            # itself (see calendar/month.html) instead of cluttering the
            # sidebar with two more entries.
            NavNode(key="calendar-view", label="Month View", href="/calendar", order=1),
            NavNode(key="calendar-new", label="New Entry", href="/calendar/new", order=2),
        ],
    )
)
