"""Models for the `control` schema: platform-wide, not tenant-scoped.

Every table here carries an explicit schema="control", so it is unaffected
by the schema_translate_map used for tenant-scoped queries (see
rain.db.base). One instance of these tables exists, period.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

CONTROL_SCHEMA = "control"


class ControlBase(DeclarativeBase):
    pass


class Tenant(ControlBase):
    __tablename__ = "tenants"
    __table_args__ = {"schema": CONTROL_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    schema_name: Mapped[str] = mapped_column(String(63), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(ControlBase):
    """RBAC role. Seeded with exactly `internal_admin` and `client`, but a
    table (not a hardcoded enum) so adding finer-grained roles later is an
    admin action, not a migration."""

    __tablename__ = "roles"
    __table_args__ = {"schema": CONTROL_SCHEMA}

    key: Mapped[str] = mapped_column(String(63), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class User(ControlBase):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL for internal_admin (cross-tenant); required for client users.
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    # NULL for an LDAP-sourced user (auth_source == "ldap") -- that user
    # never gets a local password at all; every login binds live against
    # the directory instead (see rain.modules.auth.provider). Required for
    # a "local" user, enforced at the app layer where such a user is
    # created, same trade-off this codebase already makes elsewhere for
    # conditionally-required columns.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_key: Mapped[str] = mapped_column(ForeignKey(f"{CONTROL_SCHEMA}.roles.key"))
    display_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # local | ldap. Set once at creation (by the admin "New user" form for
    # local, by the LDAP sync for ldap) and not meant to change afterwards.
    auth_source: Mapped[str] = mapped_column(String(15), default="local", server_default="local")
    # The user's full distinguished name in the directory -- only set for
    # auth_source == "ldap", used to bind-authenticate them at login.
    ldap_dn: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant | None] = relationship()
    role: Mapped[Role] = relationship()


class Session(ControlBase):
    """DB-backed session. Cookie holds an opaque token; only its sha256 hash
    is stored, so a DB leak doesn't hand out live sessions."""

    __tablename__ = "sessions"
    __table_args__ = {"schema": CONTROL_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="CASCADE"))
    active_tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.tenants.id", ondelete="SET NULL"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class GlobalConfig(ControlBase):
    """Instance-wide runtime configuration (branding, instance name, ...).
    See rain.core.config_store for the cached read path."""

    __tablename__ = "global_config"
    __table_args__ = {"schema": CONTROL_SCHEMA}

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
    )


class AuthProviderConfig(ControlBase):
    """local | oidc | saml | ldap. Only `local` is functional in this
    milestone; the others exist so Admin UI can show them as configurable
    placeholders ("coming soon") without a later schema change."""

    __tablename__ = "auth_providers"
    __table_args__ = {"schema": CONTROL_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(31))
    name: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Fernet-encrypted JSON (rain.core.crypto) -- where an actual secret
    # (the LDAP bind password) needs to live, unlike the plain `config`
    # column above which predates having any provider with a real secret
    # to store.
    config_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyslogSourceMap(ControlBase):
    """Routes an incoming syslog event to a tenant, matched against `host`
    or `program` before the event is written into any tenant schema (the
    tenant isn't known yet at that point, so this table has to live in
    `control`). Evaluated in `sort_order`; first match wins. A pattern of
    `.*` with is_regex=true acts as a catch-all / default tenant.

    action="discard" is a negation rule instead: a matching event is
    dropped by the listener before it's ever persisted or routed
    (tenant_id is None for these -- there's nothing to route to). Backs
    the tickets/live "Discard these" bulk action, for muting noisy
    sources without a tenant seeing (and having to individually dismiss)
    every occurrence."""

    __tablename__ = "syslog_source_map"
    __table_args__ = {"schema": CONTROL_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey(f"{CONTROL_SCHEMA}.tenants.id", ondelete="CASCADE"))
    match_field: Mapped[str] = mapped_column(String(15))  # host | program
    pattern: Mapped[str] = mapped_column(String(255))
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    action: Mapped[str] = mapped_column(String(10), default="route", server_default="route")  # route | discard
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant | None] = relationship()


class AuditLog(ControlBase):
    """Platform-level events: tenant/user/role/branding changes. Per-tenant
    asset changes are logged in each tenant schema's own audit_log instead
    (see rain.db.tenant_models.AuditLog)."""

    __tablename__ = "audit_log"
    __table_args__ = {"schema": CONTROL_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(127))
    entity_type: Mapped[str] = mapped_column(String(127))
    entity_id: Mapped[str | None] = mapped_column(String(127), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
