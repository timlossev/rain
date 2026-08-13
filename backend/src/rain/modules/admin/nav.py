from __future__ import annotations

from rain.core.nav_registry import NavNode, nav_registry

nav_registry.register(
    NavNode(
        key="admin",
        label="Admin",
        icon="settings",
        href="/admin",
        order=90,
        roles=("internal_admin",),
        children=[
            NavNode(key="admin-branding", label="Branding", href="/admin/branding", order=1, roles=("internal_admin",)),
            NavNode(key="admin-tenants", label="Tenants", href="/admin/tenants", order=2, roles=("internal_admin",)),
            NavNode(key="admin-users", label="Users", href="/admin/users", order=3, roles=("internal_admin",)),
            NavNode(
                key="admin-auth-providers",
                label="Auth Providers",
                href="/admin/auth-providers",
                order=4,
                roles=("internal_admin",),
            ),
            NavNode(key="admin-smtp", label="SMTP Relay", href="/admin/smtp", order=5, roles=("internal_admin",)),
            NavNode(
                key="admin-syslog-sources",
                label="Syslog Sources",
                href="/admin/syslog-sources",
                order=6,
                roles=("internal_admin",),
            ),
            NavNode(
                key="admin-ticket-statuses",
                label="Ticket Statuses",
                href="/admin/ticket-statuses",
                order=7,
                roles=("internal_admin",),
            ),
            NavNode(
                key="admin-notification-channels",
                label="Notification Channels",
                href="/admin/notification-channels",
                order=8,
                roles=("internal_admin",),
            ),
            NavNode(key="admin-groups", label="Groups", href="/admin/groups", order=9, roles=("internal_admin",)),
            NavNode(
                key="admin-approval-flows",
                label="Approval Flows",
                href="/admin/approval-flows",
                order=10,
                roles=("internal_admin",),
            ),
        ],
    )
)
