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
        ],
    )
)
