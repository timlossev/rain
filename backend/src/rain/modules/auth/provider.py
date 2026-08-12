"""Auth providers. `authenticate_local` is the only functional provider in
this milestone. OIDC/SAML/LDAP would each add a sibling
`authenticate_<provider>()` here, selected by `provider_type` from
control.auth_providers -- those rows already exist (seeded disabled by the
initial migration), ready for a later release to implement."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.security import verify_password
from rain.db.control_models import User


async def authenticate_local(session: AsyncSession, email: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
