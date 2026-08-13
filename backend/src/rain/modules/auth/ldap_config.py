"""Loads/saves the single `auth_providers` row with provider_type == "ldap".
Shared by the login-time bind check (rain.modules.auth.provider), the
periodic sync (rain.modules.auth.ldap_sync), and the Admin UI
(rain.modules.admin.router) -- one place that knows the config's shape and
how it's encrypted at rest, instead of three.

Deliberately a single row/single directory, matching how `auth_providers`
already ships (one seeded row per provider_type, see migrations/control/
versions/0001_initial.py) rather than a table of arbitrarily many LDAP
connections -- every synced user and group lands in the one tenant this
config names. Multiple independent directories (e.g. one per tenant) would
need loosening that one-row assumption; not built here since it wasn't
asked for and the "one row per provider_type" shape is already load-bearing
elsewhere (the Admin > Auth Providers list).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.crypto import decrypt_json, encrypt_json
from rain.db.control_models import AuthProviderConfig

PROVIDER_TYPE = "ldap"


@dataclass(frozen=True)
class LdapConfig:
    server_uri: str
    use_starttls: bool
    bind_dn: str
    bind_password: str
    user_base_dn: str
    user_filter: str
    user_email_attr: str
    user_name_attr: str
    group_base_dn: str
    group_filter: str
    group_name_attr: str
    group_member_attr: str
    target_tenant_id: int
    sync_interval_minutes: int


_DEFAULTS = {
    "server_uri": "",
    "use_starttls": False,
    "bind_dn": "",
    "bind_password": "",
    "user_base_dn": "",
    "user_filter": "(objectClass=inetOrgPerson)",
    "user_email_attr": "mail",
    "user_name_attr": "displayName",
    "group_base_dn": "",
    "group_filter": "(objectClass=groupOfNames)",
    "group_name_attr": "cn",
    "group_member_attr": "member",
    "target_tenant_id": None,
    "sync_interval_minutes": 60,
}


async def get_provider_row(session: AsyncSession) -> AuthProviderConfig | None:
    result = await session.execute(select(AuthProviderConfig).where(AuthProviderConfig.provider_type == PROVIDER_TYPE))
    return result.scalar_one_or_none()


def _decode(row: AuthProviderConfig) -> dict:
    data = dict(_DEFAULTS)
    if row.config_encrypted:
        data.update(decrypt_json(row.config_encrypted))
    return data


async def get_ldap_config(session: AsyncSession) -> LdapConfig | None:
    """None if the row doesn't exist, isn't enabled, or has no target
    tenant configured yet -- callers treat all three the same way (LDAP
    isn't usable right now)."""
    row = await get_provider_row(session)
    if row is None or not row.is_enabled:
        return None
    data = _decode(row)
    if not data.get("target_tenant_id") or not data.get("server_uri") or not data.get("bind_dn"):
        return None
    return LdapConfig(**{k: data[k] for k in _DEFAULTS})


async def get_raw_config(session: AsyncSession) -> dict:
    """For the Admin form -- includes is_enabled-independent values (the
    form needs to show what's saved even while the toggle is off) but
    never includes bind_password verbatim in a context that gets logged;
    the form template masks it."""
    row = await get_provider_row(session)
    if row is None:
        return dict(_DEFAULTS)
    return _decode(row)


async def save_ldap_config(session: AsyncSession, *, is_enabled: bool, **fields) -> None:
    row = await get_provider_row(session)
    if row is None:
        row = AuthProviderConfig(provider_type=PROVIDER_TYPE, name="LDAP", config={})
        session.add(row)
    merged = dict(_DEFAULTS)
    if row.config_encrypted:
        merged.update(decrypt_json(row.config_encrypted))
    merged.update(fields)
    row.config_encrypted = encrypt_json(merged)
    row.is_enabled = is_enabled
    await session.commit()
