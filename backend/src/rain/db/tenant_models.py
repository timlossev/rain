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

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


class TicketStatus(TenantBase):
    """Per-tenant customizable ticket status ('Open', 'In Progress', ...).
    Ticket.status stores this row's `key` as a plain string rather than a
    real FK -- app-validated (rain.modules.tickets.service.update_status),
    same trade-off this codebase already makes for other loosely-coupled
    references, and it avoids having to decide what happens to existing
    tickets' status column on a hard FK when an admin deletes a status."""

    __tablename__ = "ticket_statuses"
    __table_args__ = (UniqueConstraint("key", name="uq_ticket_statuses_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(31))
    label: Mapped[str] = mapped_column(String(63))
    color: Mapped[str] = mapped_column(String(7), default="#6b7280", server_default="#6b7280")
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    status_changes: Mapped[list["TicketStatusChange"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketStatusChange.created_at"
    )
    rule_triggers: Mapped[list["PlatformEventTrigger"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="PlatformEventTrigger.created_at"
    )


class TicketComment(TenantBase):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="comments")


class TicketStatusChange(TenantBase):
    """Audit trail entry for a status transition -- shown interleaved with
    comments in the ticket detail activity feed. `from_status` is null for
    a ticket's very first status (there's nothing to transition from)."""

    __tablename__ = "ticket_status_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(31), nullable=True)
    to_status: Mapped[str] = mapped_column(String(31))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="status_changes")


class NotificationChannel(TenantBase):
    """email | slack. Config is Fernet-encrypted at rest (recipient list /
    webhook URL), same helper as SyncConnection.config_encrypted. The SMTP
    relay itself is instance-wide (control.global_config, set by
    internal_admin) -- this table only holds who gets notified for this
    tenant and through which channel.

    No longer carries notify_on_incident/notify_on_vulnerability: those
    drove an unconditional "notify on every ticket of this type" firing
    that ran in parallel with (and was a strict subset of) Platform Event
    rules -- a rule with an action pointed at this channel and pattern
    ".*" covers the same case, explicitly and visibly, so the always-on
    duplicate was removed rather than kept as a second code path (see
    migration 0006)."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_type: Mapped[str] = mapped_column(String(15))  # email | slack
    name: Mapped[str] = mapped_column(String(255))
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(TenantBase):
    """A DOC-xxxxxx knowledge-base entry. The file itself lives in a
    storage backend (rain.modules.documents.storage -- local volume today,
    swappable for S3 later); `storage_key` is that backend's opaque
    identifier, not a filesystem path callers should ever build by hand."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_number: Mapped[str] = mapped_column(String(31), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(127), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    uploaded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    links: Mapped[list["DocumentLink"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentLink(TenantBase):
    """Polymorphic association: a document linked to an asset or a ticket.
    No real FK to either target (they're different tables), so
    `linked_type`/`linked_id` are app-validated, same trade-off as the
    cross-schema integers elsewhere in this file."""

    __tablename__ = "document_links"
    __table_args__ = (
        UniqueConstraint("document_id", "linked_type", "linked_id", name="uq_document_links"),
        Index("ix_document_links_target", "linked_type", "linked_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    linked_type: Mapped[str] = mapped_column(String(15))  # asset | ticket
    linked_id: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="links")


class PlatformEventRule(TenantBase):
    """A rule that fires one or more actions when a platform event occurs
    (today: a ticket of a given type is created) and `pattern` matches.
    Unlike TicketRule (syslog -> ticket promotion, first match wins), every
    active matching platform event rule fires -- this is a downstream
    reaction layer, not a routing decision, so multiple rules can react to
    the same ticket."""

    __tablename__ = "platform_event_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    trigger_event: Mapped[str] = mapped_column(String(31))  # incident_created | vulnerability_created
    match_field: Mapped[str] = mapped_column(String(15), default="title", server_default="title")  # title | description
    pattern: Mapped[str] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actions: Mapped[list["PlatformEventAction"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="PlatformEventAction.id"
    )


class PlatformEventAction(TenantBase):
    """One action a PlatformEventRule fires on match. `config` shape depends
    on action_type:
      notify_slack / notify_email -> {"channel_id": <NotificationChannel.id>}
      webhook                     -> {"url": str, "payload_template": str}
      attach_document              -> {"document_id": int}
      attach_asset                 -> {"asset_id": int}
    Reuses NotificationChannel for the Slack/email actions rather than
    storing a second copy of webhook URLs/recipient lists."""

    __tablename__ = "platform_event_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("platform_event_rules.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(31))
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped[PlatformEventRule] = relationship(back_populates="actions")


class PlatformEventTrigger(TenantBase):
    """Audit trail: this rule fired for this ticket, with a human-readable
    summary of what each action did. `rule_name` is a snapshot (kept even
    if the rule is later edited/deleted) so the ticket's history stays
    meaningful; `rule_id` itself is SET NULL on rule deletion rather than
    cascading, so the log entry survives."""

    __tablename__ = "platform_event_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("platform_event_rules.id", ondelete="SET NULL"), nullable=True)
    rule_name: Mapped[str] = mapped_column(String(255))
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="rule_triggers")


class CalendarEntry(TenantBase):
    """Per-tenant calendar: one-off or recurring dated entries (renewals,
    maintenance windows, audits...). `recurrence` is one of the fixed
    presets below or null for a one-time entry -- occurrences are computed
    on the fly (rain.modules.calendar.recurrence), never materialized as
    rows, so a recurring entry stays a single record no matter how far out
    it's projected.

    `emit_syslog_event`/`event_program` are the bridge requested to make
    calendar entries usable as Event Policy triggers: when an occurrence
    falls due, the worker synthesizes a SyslogEvent exactly as if it had
    arrived over the wire (rain.modules.calendar.sweep), so the *existing*
    rule engine (TicketRule/Platform Events) reacts to it with no separate
    calendar-specific rule system needed. `last_fired_date` is the sweep's
    own dedup marker (one synthetic event per occurrence, not one per
    sweep tick).

    `policy_ref` is an inert, opaque JSON blob -- a forward-looking hook
    for a future "recurring policy" concept (e.g. "update document X
    quarterly") that doesn't exist yet. Nothing reads it today; it exists
    now purely so it round-trips through .ics export/import (as a custom
    X-RAIN-POLICY property) without a later migration."""

    __tablename__ = "calendar_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[dt.date] = mapped_column(Date)
    recurrence: Mapped[str | None] = mapped_column(String(15), nullable=True)  # null|quarterly|biannual|annual
    recurrence_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    emit_syslog_event: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    event_program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_fired_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
