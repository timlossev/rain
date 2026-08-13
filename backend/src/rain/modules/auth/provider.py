"""Auth providers. `authenticate_local` (password hash check) and
`authenticate_ldap` (live directory bind) are the two functional providers;
`authenticate_user` dispatches between them by the user's own
`auth_source`, set once at creation and not meant to change afterwards.
OIDC/SAML would each add a sibling `authenticate_<provider>()` here --
those rows already exist too (seeded disabled by the initial migration),
ready for a later release to implement.

Local sign-in is unaffected by any of this: a "local" user still just
gets their password checked, exactly as before LDAP existed. Only a
user whose auth_source is "ldap" (created by the LDAP sync, see
rain.modules.auth.ldap_sync) is routed to a live bind instead -- they
never have a usable password_hash to check in the first place."""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core import ldap_client
from rain.core.security import verify_password
from rain.db.control_models import User
from rain.modules.auth.ldap_config import get_ldap_config


async def authenticate_local(session: AsyncSession, email: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None or user.password_hash is None or not verify_password(password, user.password_hash):
        return None
    return user


async def authenticate_ldap(session: AsyncSession, user: User, password: str) -> bool:
    """Binds to the directory AS `user` with the password they just
    submitted -- RAIN never stores or otherwise persists it. False (not an
    exception) on any failure: an LDAP outage or a misconfigured bind is
    exactly as much "can't log this user in right now" as a wrong
    password from the caller's perspective, and login_submit's generic
    "Invalid email or password" message is the right response to both."""
    if not user.ldap_dn:
        return False
    config = await get_ldap_config(session)
    if config is None:
        return False
    return await asyncio.to_thread(
        ldap_client.authenticate_user, config.server_uri, user.ldap_dn, password, config.use_starttls
    )


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if user.auth_source == "ldap":
        return user if await authenticate_ldap(session, user, password) else None
    if user.password_hash is None or not verify_password(password, user.password_hash):
        return None
    return user
