from __future__ import annotations

from rain.core.nav_registry import NavNode, nav_registry

# Tenant-scoped admin functions -- both internal_admin (cross-tenant) and
# client_admin (jailed to their one tenant, see rain.core.rbac.
# require_admin) can reach these; the tenant scoping itself comes for
# free from schema-per-tenant (get_tenant_db is already bound to the
# session's one active tenant, so there's no query here that could ever
# reach another tenant's rows regardless of which of these two roles is
# asking).
_TENANT_ADMIN_ROLES = ("internal_admin", "client_admin")

nav_registry.register(
    NavNode(
        key="admin",
        label="Admin",
        icon="settings",
        href="/admin",
        order=90,
        roles=_TENANT_ADMIN_ROLES,
        children=[
            # Platform-wide settings -- each one either spans every tenant
            # (Tenants, Users, Auth Providers, syslog routing) or configures
            # something instance-wide (Branding, SMTP relay). internal_admin
            # only; a client_admin doesn't even see this submenu.
            NavNode(
                key="admin-platform",
                label="Platform Administration",
                order=1,
                roles=("internal_admin",),
                children=[
                    NavNode(key="admin-branding", label="Branding", href="/admin/branding", order=1, roles=("internal_admin",)),
                    NavNode(key="admin-tenants", label="Tenants", href="/admin/tenants", order=2, roles=("internal_admin",)),
                    NavNode(
                        key="admin-auth-providers",
                        label="Auth Providers",
                        href="/admin/auth-providers",
                        order=3,
                        roles=("internal_admin",),
                    ),
                    NavNode(key="admin-smtp", label="SMTP Relay", href="/admin/smtp", order=4, roles=("internal_admin",)),
                    NavNode(
                        key="admin-syslog-sources",
                        label="Syslog Listener",
                        href="/admin/syslog-sources",
                        order=5,
                        roles=("internal_admin",),
                    ),
                    # Last in this submenu on purpose -- directly above
                    # Tenant Administration's own first item, Groups, so
                    # the two land next to each other in the rendered menu
                    # (people/accounts vs. groups of them being far apart
                    # in a flat list was confusing).
                    NavNode(key="admin-users", label="Users", href="/admin/users", order=6, roles=("internal_admin",)),
                    # rain.modules.admin.config_bundle -- export/import for
                    # everything on this submenu that's genuinely instance-
                    # wide (branding, SMTP, LDAP/SAML, syslog routing).
                    # The tenant half of the same page is reached via
                    # admin-tenant-config-bundle below instead, same split
                    # Branding itself already uses.
                    NavNode(
                        key="admin-config-bundle",
                        label="Config Bundles",
                        href="/admin/config-bundle",
                        order=7,
                        roles=("internal_admin",),
                    ),
                    # The Swagger UI at /docs -- gated the same way as
                    # every other platform-wide setting (require_internal_
                    # admin, see rain.main's route for it), not FastAPI's
                    # own public default.
                    NavNode(key="admin-api-docs", label="API Documentation", href="/docs", order=8, roles=("internal_admin",)),
                ],
            ),
            # Tenant-scoped settings -- reachable by internal_admin (for
            # whichever tenant is currently active) or client_admin (for
            # their one pinned tenant).
            NavNode(
                key="admin-tenant",
                label="Tenant Administration",
                order=2,
                roles=_TENANT_ADMIN_ROLES,
                children=[
                    # First in this submenu on purpose -- see Users' own
                    # comment above.
                    NavNode(key="admin-groups", label="Groups", href="/admin/groups", order=1, roles=_TENANT_ADMIN_ROLES),
                    NavNode(
                        key="admin-ticket-statuses",
                        label="Ticket Statuses",
                        href="/admin/ticket-statuses",
                        order=2,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    NavNode(
                        key="admin-notification-channels",
                        label="Notification Channels",
                        href="/admin/notification-channels",
                        order=3,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    NavNode(
                        key="admin-approval-flows",
                        label="Approval Flows",
                        href="/admin/approval-flows",
                        order=4,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    # Covers what used to be a separate Correlation Rules
                    # screen too -- unified into one TicketRule table/UI
                    # (promotion_type: single | repetition | ml_anomaly),
                    # see rain.db.tenant_models.TicketRule's own docstring
                    # and migration 0038.
                    NavNode(
                        key="admin-event-promotion-policies",
                        label="Event Promotion Policies",
                        href="/tickets/rules/all",
                        order=5,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    NavNode(
                        key="admin-platform-response-rules",
                        label="Platform Response Rules",
                        href="/tickets/platform-events",
                        order=6,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    NavNode(
                        key="admin-webhooks",
                        label="Webhooks",
                        href="/admin/webhooks",
                        order=7,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    # Moved here from the Assets menu -- defining the
                    # asset schema itself reads as an administration
                    # function, not a day-to-day Assets task.
                    NavNode(
                        key="admin-asset-types",
                        label="Asset Types",
                        href="/assets/types",
                        order=8,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    # Defines what shows up on /catalog and the portal's
                    # own Catalog tab (rain.modules.catalog) -- same
                    # "designing the schema is an admin function" reasoning
                    # as Asset Types above.
                    NavNode(
                        key="admin-service-catalog",
                        label="Service Catalog",
                        href="/admin/catalog",
                        order=9,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    # Bulk-defines ticket custom fields from an uploaded
                    # spreadsheet's header row (+ sample data, best-effort
                    # type-guessed) -- same "designing the schema is an
                    # admin function" reasoning as Asset Types/Service
                    # Catalog above, and gated require_admin to match
                    # (rain.modules.tickets.router.field_pack_form), unlike
                    # the one-at-a-time Custom Fields screen under Records
                    # Authority, which keeps its own pre-existing
                    # require_login gate.
                    NavNode(
                        key="admin-ticket-field-pack",
                        label="Import Ticket Field Pack",
                        href="/tickets/fields/import-pack",
                        order=10,
                        roles=_TENANT_ADMIN_ROLES,
                    ),
                    # Same /admin/branding page Platform Administration's
                    # own "Branding" entry points at (it shows the
                    # instance-wide section only to internal_admin) --
                    # client_admin only here, so they still have a way to
                    # reach their tenant's portal settings without also
                    # duplicating an internal_admin's already-existing
                    # link to the same page above.
                    NavNode(
                        key="admin-incident-portal",
                        label="Incident Portal",
                        href="/admin/branding",
                        order=11,
                        roles=("client_admin",),
                    ),
                    # Same /admin/config-bundle page admin-config-bundle
                    # above points at (it shows the platform card only to
                    # internal_admin) -- client_admin only here, same
                    # "duplicate link" avoidance as admin-incident-portal.
                    NavNode(
                        key="admin-tenant-config-bundle",
                        label="Config Bundle",
                        href="/admin/config-bundle",
                        order=12,
                        roles=("client_admin",),
                    ),
                ],
            ),
        ],
    )
)
