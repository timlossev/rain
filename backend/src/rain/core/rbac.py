"""Role-gating dependency factory. Roles come from control.roles (seeded
with internal_admin/client/client_admin, see migrations/control/versions/
0001_initial.py and 0007_client_admin_role.py) rather than a hardcoded
enum, so adding another role later is an admin action, not a migration.

Three roles today: `internal_admin` (platform operator, every tenant,
every setting), `client` (one tenant, no admin functions), `client_admin`
(one tenant -- pinned exactly like `client`, see rain.core.tenancy's
is_internal_admin check -- but with admin rights over that one tenant's
own settings). client_admin is deliberately *not* a third tier above
client in require_login/require_admin below so much as a sibling of
client that also passes require_admin -- see each route's own choice of
require_login vs require_admin for what that means for it."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from rain.core.tenancy import CurrentUser, get_current_user


def require_role(*roles: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role_key not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
        return user

    return _dep


require_login = require_role("internal_admin", "client", "client_admin")
require_internal_admin = require_role("internal_admin")
# Tenant-scoped admin functions (Ticket Statuses, Notification Channels,
# Groups, Approval Flows, Webhooks, Event Promotion Policies, Correlation
# Rules, Platform Response Rules): internal_admin can reach these for
# whichever tenant is currently active, client_admin only for their one
# pinned tenant -- there is no query path here that could reach another
# tenant's data regardless of which of the two is asking, since
# get_tenant_db is already bound to the caller's one active tenant.
# Platform-wide settings (branding, tenants, users, auth providers, SMTP
# relay, syslog routing) stay on require_internal_admin instead, not this.
require_admin = require_role("internal_admin", "client_admin")
