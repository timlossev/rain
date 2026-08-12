"""Role-gating dependency factory. Roles come from control.roles (seeded
with internal_admin/client, see migrations/control/versions/0001_initial.py)
rather than a hardcoded enum, so adding a role later is an admin action."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from rain.core.tenancy import CurrentUser, get_current_user


def require_role(*roles: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role_key not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
        return user

    return _dep


require_login = require_role("internal_admin", "client")
require_internal_admin = require_role("internal_admin")
