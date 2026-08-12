"""Models applied once per tenant, into a dedicated `tenant_<slug>` schema.

None of these tables declare an explicit `schema=`, which is what lets
rain.db.base's schema_translate_map redirect them to whichever tenant
schema the current request is scoped to -- the exact same model classes
serve every tenant.

Postgres cannot enforce foreign keys across schemas, so references back
into the control schema (e.g. Asset.owner_user_id -> control.users) are
plain integers, validated at the application layer instead of the DB --
a documented trade-off of schema-per-tenant multi-tenancy.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class TenantBase(DeclarativeBase):
    pass


class AssetType(TenantBase):
    __tablename__ = "asset_types"
    __table_args__ = (UniqueConstraint("key", name="uq_asset_types_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(255))
    icon: Mapped[str | None] = mapped_column(String(63), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    custom_fields: Mapped[list["CustomField"]] = relationship(back_populates="asset_type")


class CustomField(TenantBase):
    """A key/value field describing an asset. `asset_type_id` NULL means the
    field applies to every asset type in this tenant."""

    __tablename__ = "custom_fields"
    __table_args__ = (UniqueConstraint("asset_type_id", "field_key", name="uq_custom_fields_type_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type_id: Mapped[int | None] = mapped_column(ForeignKey("asset_types.id", ondelete="CASCADE"), nullable=True)
    field_key: Mapped[str] = mapped_column(String(63))
    label: Mapped[str] = mapped_column(String(255))
    # text | number | boolean | date | url | email | select -- validated at
    # the API layer (rain.modules.assets.schemas.FieldType), not the DB, to
    # avoid juggling a Postgres ENUM type per tenant schema.
    field_type: Mapped[str] = mapped_column(String(15), default="text", server_default="text")
    select_options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    asset_type: Mapped[AssetType | None] = relationship(back_populates="custom_fields")


class Asset(TenantBase):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("external_id", name="uq_assets_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type_id: Mapped[int] = mapped_column(ForeignKey("asset_types.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(63), default="active", server_default="active")
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    asset_type: Mapped[AssetType] = relationship()
    field_values: Mapped[list["AssetFieldValue"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class AssetFieldValue(TenantBase):
    """EAV storage for custom field values."""

    __tablename__ = "asset_field_values"
    __table_args__ = (UniqueConstraint("asset_id", "field_id", name="uq_asset_field_values"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_fields.id", ondelete="CASCADE"))
    value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    asset: Mapped[Asset] = relationship(back_populates="field_values")
    field: Mapped[CustomField] = relationship()


class ExportProfile(TenantBase):
    """Saved column/header/order preset for CSV/JSON export. Export also
    accepts an ad-hoc spec without saving one of these."""

    __tablename__ = "export_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    asset_type_id: Mapped[int | None] = mapped_column(ForeignKey("asset_types.id", ondelete="CASCADE"), nullable=True)
    format: Mapped[str] = mapped_column(String(15), default="csv", server_default="csv")
    columns: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncConnection(TenantBase):
    """Cloud asset-sync connection. Discovery/apply are stubbed
    (NotImplementedError) until the next release -- see
    rain.modules.assets.sync."""

    __tablename__ = "sync_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(15))  # aws | azure
    name: Mapped[str] = mapped_column(String(255))
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs: Mapped[list["SyncRun"]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class SyncRun(TenantBase):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sync_connection_id: Mapped[int] = mapped_column(ForeignKey("sync_connections.id", ondelete="CASCADE"))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(31), default="pending", server_default="pending")
    summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    connection: Mapped[SyncConnection] = relationship(back_populates="runs")


class TenantConfig(TenantBase):
    """Per-tenant runtime settings (event retention, etc.) -- the same
    key/value pattern as control.global_config, scoped to one tenant
    instead of the whole instance."""

    __tablename__ = "tenant_config"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SyslogEvent(TenantBase):
    """A syslog line received by the worker and routed to this tenant (see
    control.SyslogSourceMap). Trimmed on a retention schedule -- this is a
    rolling window, not permanent storage; promote anything worth keeping
    into a Ticket."""

    __tablename__ = "syslog_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    facility: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # syslog severity 0 (emerg) - 7 (debug)
    message: Mapped[str] = mapped_column(Text)
    raw: Mapped[str] = mapped_column(Text)
    promoted_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)


class TicketRule(TenantBase):
    """Regex-based auto-promotion: an active syslog event matching `pattern`
    against `match_field` becomes a ticket of `ticket_type`. Evaluated in
    `sort_order`; first match wins (a message doesn't spawn two tickets)."""

    __tablename__ = "ticket_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ticket_type: Mapped[str] = mapped_column(String(15))  # incident | vulnerability
    match_field: Mapped[str] = mapped_column(String(15), default="message", server_default="message")  # message|host|program
    pattern: Mapped[str] = mapped_column(String(500))
    title_template: Mapped[str] = mapped_column(String(255), default="{message}", server_default="{message}")
    severity: Mapped[str] = mapped_column(String(15), default="medium", server_default="medium")
    asset_match_field: Mapped[str | None] = mapped_column(String(15), nullable=True)  # host|program, matched to Asset.external_id
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ticket(TenantBase):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_number: Mapped[str] = mapped_column(String(31), unique=True, index=True)  # INC-000123 / VULN-000045
    ticket_type: Mapped[str] = mapped_column(String(15))  # incident | vulnerability
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="open", server_default="open")
    severity: Mapped[str] = mapped_column(String(15), default="medium", server_default="medium")
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("syslog_events.id", ondelete="SET NULL"), nullable=True)
    source_rule_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_rules.id", ondelete="SET NULL"), nullable=True)
    assignee_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reporter_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped[Asset | None] = relationship()
    comments: Mapped[list["TicketComment"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class TicketComment(TenantBase):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="comments")


class NotificationChannel(TenantBase):
    """email | slack. Config is Fernet-encrypted at rest (recipient list /
    webhook URL), same helper as SyncConnection.config_encrypted. The SMTP
    relay itself is instance-wide (control.global_config, set by
    internal_admin) -- this table only holds who gets notified for this
    tenant and through which channel."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_type: Mapped[str] = mapped_column(String(15))  # email | slack
    name: Mapped[str] = mapped_column(String(255))
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    notify_on_incident: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_on_vulnerability: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(TenantBase):
    """Per-tenant change history for asset registry entities."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(127))
    entity_type: Mapped[str] = mapped_column(String(127))
    entity_id: Mapped[str | None] = mapped_column(String(127), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
