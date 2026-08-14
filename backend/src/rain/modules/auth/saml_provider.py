"""SAML 2.0 SSO (SP-initiated). Uses python3-saml (OneLogin's toolkit) for
the actual protocol work -- AuthnRequest construction and, critically,
verifying the IdP's XML signature on the response/assertion -- rather
than hand-rolling XML-DSig verification, which is exactly the kind of
thing that's catastrophic to get subtly wrong.

Flow: GET /auth/saml/login redirects to the IdP's SSO URL with an
AuthnRequest (unsigned -- RAIN doesn't collect an SP private key in the
admin config; the IdP signing its *response* is what actually matters
here, enforced via wantAssertionsSigned below). The IdP authenticates the
user and POSTs a SAMLResponse back to /auth/saml/acs, which this module
verifies, then finds-or-creates the corresponding control.User row and
hands back to the caller (rain.modules.auth.router) an identity to mint a
normal RAIN session from -- from that point on, a SAML-sourced user looks
like any other logged-in user to the rest of the app.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Request
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.control_models import User
from rain.modules.auth.saml_config import SamlConfig

logger = logging.getLogger("rain.saml")


async def _request_data(request: Request) -> dict:
    """Adapts a Starlette/FastAPI Request into the plain dict python3-saml
    expects -- it ships adapters for Flask/Django only, nothing for ASGI."""
    form: dict = {}
    if request.method == "POST":
        form = dict(await request.form())
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.url.hostname,
        "server_port": request.url.port or (443 if request.url.scheme == "https" else 80),
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": form,
    }


def _base_url(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _settings_dict(config: SamlConfig, base_url: str) -> dict:
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": config.sp_entity_id,
            "assertionConsumerService": {
                "url": f"{base_url}/auth/saml/acs",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
        },
        "idp": {
            "entityId": config.idp_entity_id,
            "singleSignOnService": {
                "url": config.idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": config.idp_x509_cert,
        },
        "security": {
            "authnRequestsSigned": False,
            # The one setting that actually matters for security: refuse
            # any response whose assertion isn't signed by the IdP cert
            # configured above. python3-saml verifies this signature
            # cryptographically (via xmlsec) rather than us trusting
            # whatever XML shows up at the ACS endpoint.
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantNameIdEncrypted": False,
            "requestedAuthnContext": False,
        },
    }


async def build_auth(request: Request, config: SamlConfig) -> OneLogin_Saml2_Auth:
    data = await _request_data(request)
    return OneLogin_Saml2_Auth(data, _settings_dict(config, _base_url(request)))


def metadata_xml(config: SamlConfig, base_url: str) -> tuple[str, list[str]]:
    """SP metadata for the IdP side of setup -- (xml, validation_errors)."""
    settings = OneLogin_Saml2_Settings(_settings_dict(config, base_url), sp_validation_only=True)
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    return (metadata.decode("utf-8") if isinstance(metadata, bytes) else metadata), errors


@dataclass
class SamlIdentity:
    subject: str  # NameID, or the configured attr_username attribute
    email: str | None
    first_name: str | None
    last_name: str | None
    role_attribute_value: str | None


def _first_attr(attributes: dict, name: str) -> str | None:
    if not name:
        return None
    values = attributes.get(name)
    return values[0] if values else None


def extract_identity(auth: OneLogin_Saml2_Auth, config: SamlConfig) -> SamlIdentity:
    attributes = auth.get_attributes() or {}
    subject = _first_attr(attributes, config.attr_username) if config.attr_username else None
    if not subject:
        subject = auth.get_nameid()
    return SamlIdentity(
        subject=subject,
        email=_first_attr(attributes, config.attr_email),
        first_name=_first_attr(attributes, config.attr_first_name),
        last_name=_first_attr(attributes, config.attr_last_name),
        role_attribute_value=_first_attr(attributes, config.attr_role),
    )


def resolve_role(config: SamlConfig, identity: SamlIdentity) -> str:
    """Least-privilege: only an exact (case-sensitive) match against the
    configured role_admin_value grants internal_admin. A different value,
    several values with none matching, or no Role attribute at all all
    fall through to "client" -- a misconfigured or IdP-side-blank Role
    claim should never silently grant admin."""
    if identity.role_attribute_value == config.role_admin_value:
        return "internal_admin"
    return "client"


async def provision_or_update_user(session: AsyncSession, config: SamlConfig, identity: SamlIdentity) -> User | None:
    """Find-or-create by email -- the natural cross-system join key
    (NameID alone is often an opaque, IdP-internal identifier, not
    something to display or match a pre-existing account against). None
    if the assertion carried no email, or if the email belongs to an
    existing non-SAML account: same "detect a collision and refuse rather
    than silently take it over" posture as rain.modules.auth.ldap_sync's
    own _sync_users, not a new policy invented here."""
    if not identity.email:
        logger.warning("SAML login: assertion for %s carried no email attribute -- refused", identity.subject)
        return None
    email = identity.email.strip().lower()
    display_name = " ".join(p for p in (identity.first_name, identity.last_name) if p) or email
    role_key = resolve_role(config, identity)

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is not None and user.auth_source != "saml":
        logger.warning("SAML login: %s already exists as a %s account (email collision) -- refused", email, user.auth_source)
        return None

    # NULL tenant_id for internal_admin (cross-tenant, same as a local or
    # LDAP internal_admin) -- only a "client" gets pinned to the
    # configured target tenant. Re-derived on every login alongside
    # role_key itself, so a promotion/demotion in the IdP takes effect
    # immediately rather than only at first provisioning.
    tenant_id = None if role_key == "internal_admin" else config.target_tenant_id

    if user is None:
        user = User(
            tenant_id=tenant_id,
            email=email,
            password_hash=None,
            role_key=role_key,
            display_name=display_name,
            auth_source="saml",
            is_active=True,
        )
        session.add(user)
    else:
        user.display_name = display_name
        user.role_key = role_key
        user.tenant_id = tenant_id
        user.is_active = True
    await session.commit()
    return user
