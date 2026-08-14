"""Loads/saves the single `auth_providers` row with provider_type == "saml".
Same shape and same "one row, one directory/IdP" trade-off as
rain.modules.auth.ldap_config -- see that module's docstring for why.

Shared by the SSO flow itself (rain.modules.auth.saml_provider) and the
Admin UI (rain.modules.admin.router) -- one place that knows the config's
shape and how it's encrypted at rest, instead of two.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.core.crypto import decrypt_json, encrypt_json
from rain.db.control_models import AuthProviderConfig

PROVIDER_TYPE = "saml"


@dataclass(frozen=True)
class SamlConfig:
    idp_entity_id: str
    idp_sso_url: str
    idp_x509_cert: str
    sp_entity_id: str
    # Which assertion attribute carries each value. attr_username blank
    # means "use the assertion's <NameID> element itself" -- the
    # SAML-standard place for the subject's identifier -- rather than a
    # separate attribute; set it only if your IdP puts the actual
    # username somewhere else (e.g. NameID is a persistent, opaque ID).
    attr_username: str
    attr_email: str
    attr_first_name: str
    attr_last_name: str
    attr_role: str
    # The exact value the Role attribute must equal (case-sensitive) for
    # RAIN to grant internal_admin; anything else -- a different value,
    # multiple values with no match, or the attribute missing entirely --
    # grants "client" instead. Least-privilege default: a misconfigured
    # or absent Role claim never silently grants admin.
    role_admin_value: str
    target_tenant_id: int


_DEFAULTS = {
    "idp_entity_id": "",
    "idp_sso_url": "",
    "idp_x509_cert": "",
    "sp_entity_id": "",
    "attr_username": "",
    "attr_email": "email",
    "attr_first_name": "firstName",
    "attr_last_name": "lastName",
    "attr_role": "role",
    "role_admin_value": "internal_admin",
    "target_tenant_id": None,
}


async def get_provider_row(session: AsyncSession) -> AuthProviderConfig | None:
    result = await session.execute(select(AuthProviderConfig).where(AuthProviderConfig.provider_type == PROVIDER_TYPE))
    return result.scalar_one_or_none()


def _decode(row: AuthProviderConfig) -> dict:
    data = dict(_DEFAULTS)
    if row.config_encrypted:
        data.update(decrypt_json(row.config_encrypted))
    return data


async def get_saml_config(session: AsyncSession) -> SamlConfig | None:
    """None if the row doesn't exist, isn't enabled, or is missing any of
    the fields required to actually build a SAML request/validate a
    response -- callers treat all of these the same way (SSO isn't usable
    right now)."""
    row = await get_provider_row(session)
    if row is None or not row.is_enabled:
        return None
    data = _decode(row)
    required = ("idp_entity_id", "idp_sso_url", "idp_x509_cert", "sp_entity_id", "target_tenant_id")
    if any(not data.get(k) for k in required):
        return None
    return SamlConfig(**{k: data[k] for k in _DEFAULTS})


async def get_raw_config(session: AsyncSession) -> dict:
    """For the Admin form -- includes is_enabled-independent values (the
    form needs to show what's saved even while the toggle is off)."""
    row = await get_provider_row(session)
    if row is None:
        return dict(_DEFAULTS)
    return _decode(row)


async def save_saml_config(session: AsyncSession, *, is_enabled: bool, **fields) -> None:
    row = await get_provider_row(session)
    if row is None:
        row = AuthProviderConfig(provider_type=PROVIDER_TYPE, name="SAML", config={})
        session.add(row)
    merged = dict(_DEFAULTS)
    if row.config_encrypted:
        merged.update(decrypt_json(row.config_encrypted))
    merged.update(fields)
    row.config_encrypted = encrypt_json(merged)
    row.is_enabled = is_enabled
    await session.commit()
