"""Auth providers for the password-form login path. `authenticate_user` is
the single entry point login_submit calls -- it looks the user up once,
then dispatches on their own `auth_source` (set once at creation, not
meant to change afterwards): a "local" user gets the same Argon2
password-hash check as before LDAP ever existed; a user whose
auth_source is "ldap" (created by the LDAP sync, see
rain.modules.auth.ldap_sync) is routed to `authenticate_ldap`, a live
directory bind, instead -- they never have a usable password_hash to
check in the first place.

SAML (auth_source == "saml") never goes through this module at all --
it's a browser-redirect SSO flow, not a password submitted to a form, so
there's no password to check here. See rain.modules.auth.saml_provider
for that flow and rain.modules.auth.router's /auth/saml/* routes for
where a SAML-sourced user's session actually gets minted."""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core import ldap_client
from rain.core.security import verify_password
from rain.db.control_models import User
from rain.modules.auth.ldap_config import get_ldap_config


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
