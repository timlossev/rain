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
    FetchedValue,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from rain.settings import get_settings


class TenantBase(DeclarativeBase):
    pass


# Dimension for the reserved (currently unpopulated) `embedding` columns
# below -- 1536 matches the most common embedding APIs' output size
# (e.g. OpenAI text-embedding-3-small/ada-002) as a reasonable default to
# reserve space for, not a commitment to that specific provider. Nothing
# writes or reads these columns yet -- see rain.modules.search's
# docstring for why (no LLM/embedding source wired in, so search today is
# Postgres full-text search only, via the search_vector columns instead).
EMBEDDING_DIM = 1536

# Settings.enable_pgvector (see that module) -- whether `embedding` gets
# mapped on Ticket/Document at all below. A plain module-level bool read
# once at import time, same as the setting itself: if it's off, the
# `vector` Postgres type/extension was never created (migrations 0006/
# 0023 skip it too), so the ORM must not know about the column either --
# a bare `select(Ticket)` selects every mapped column by default, and
# that would otherwise fail with "column tickets.embedding does not
# exist" the moment anything queried a ticket at all.
ENABLE_PGVECTOR = get_settings().enable_pgvector


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
    """A key/value field describing an asset or a ticket -- `scope`
    ("asset" | "ticket") distinguishes which, sharing one definitions
    table rather than duplicating the whole concept (same reasoning as
    ExportProfile.scope). `asset_type_id` only ever applies to an
    asset-scoped row (NULL there means "every asset type in this
    tenant"); a ticket-scoped row always carries NULL, since tickets
    don't have per-tenant *types* the way assets do -- a ticket-scoped
    field applies tenant-wide, across all three ticket types, not to one
    of them. See rain.modules.tickets.schemas' own field-value module
    docstring for why a ticket-scoped field also never honors
    is_required, unlike an asset-scoped one."""

    __tablename__ = "custom_fields"
    __table_args__ = (
        UniqueConstraint("scope", "asset_type_id", "field_key", name="uq_custom_fields_scope_type_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(10), default="asset", server_default="asset")
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
    ci_number: Mapped[str] = mapped_column(String(31), unique=True, index=True)  # CI-000123 -- Configuration Item
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
    accepts an ad-hoc spec without saving one of these. Shared by both
    the Assets and Tickets export screens -- `scope` ("asset" | "ticket")
    keeps each screen's profile list to its own kind rather than
    duplicating this table; asset_type_id only ever applies to an
    asset-scoped row (a ticket-scoped CustomField is always tenant-wide,
    not scoped to one of the three ticket types the way an asset one can
    be scoped to an asset type, so this stays null for every ticket-
    scoped row here too)."""

    __tablename__ = "export_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(10), default="asset", server_default="asset")
    asset_type_id: Mapped[int | None] = mapped_column(ForeignKey("asset_types.id", ondelete="CASCADE"), nullable=True)
    format: Mapped[str] = mapped_column(String(15), default="csv", server_default="csv")
    columns: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # message is what rain.modules.tickets.event_formats produced: the
    # envelope-stripped text as-is for plain syslog, or a human-readable
    # summary (CEF's Name, a JSON payload's message/rule.description,
    # a kv payload's msg=) when the message body turned out to be CEF/
    # JSON/key-value. event_format records which of those happened
    # ("plain" otherwise); parsed_fields holds everything that format's
    # parser extracted (CEF's header + Extension, the full JSON object,
    # or every key=value pair) for anything beyond that one summary
    # line -- never used for tenant routing or rule matching today, just
    # preserved so it isn't lost.
    message: Mapped[str] = mapped_column(Text)
    raw: Mapped[str] = mapped_column(Text)
    event_format: Mapped[str] = mapped_column(String(15), default="plain", server_default="plain")
    parsed_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    promoted_ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True, index=True
    )


class TicketRule(TenantBase):
    """An Event Promotion Policy: decides whether/how an active syslog
    event becomes a ticket. Evaluated once per newly-persisted event
    (rain.modules.tickets.rules.evaluate_and_promote) in `sort_order`.
    `promotion_type` picks which of three ways a rule wraps event(s) into
    a ticket:

    - "single": the plain case -- an event matching `match_field`/
      `pattern` becomes its own ticket of `ticket_type`. First
      single/repetition match for a given event wins (a message doesn't
      spawn two tickets); an "ml_anomaly" rule below never competes for
      this, see evaluate_and_promote's own docstring. A rule whose
      `ticket_type` is "change" also defaults that new ticket's
      `start_date`/`end_date` to "starts now, 24h turnaround" (see
      rules._default_change_window) and, if `approval_flow_id` is set,
      attaches that flow the same way the manual "New ticket" form and
      Service Catalog do (`service.start_approval`) -- an unset
      `approval_flow_id` still files the change, just unprotected, same
      as leaving that field blank on the manual form. Only ever applies
      to a *newly created* change ticket, never one "repetition" folds
      an occurrence into (that ticket already made its own choice at
      its own creation time).
    - "repetition": same match, but a computed title (`title_template`,
      via {message}/{host}/{program}) that equals an already-open
      ticket's folds the new occurrence into that ticket instead of
      spawning a new one -- a comment noting the repeat + is_problematic
      turned on (rain.modules.tickets.service.find_open_ticket_by_title /
      combine_event_into_ticket), so N occurrences of "the same thing"
      become one ticket accumulating history rather than N separate ones.
      This used to be a combine_by_title checkbox on every rule (0035);
      promoted to its own promotion_type here since it's a genuinely
      different shape of policy, not a modifier on "single". Optionally
      (`ml_sidecar_enabled`, see below) also runs ML anomaly detection
      on the same matched events, annotating rather than duplicating
      whatever ticket repetition already touched.
    - "ml_anomaly": scores every matching event (blank/`.*` `pattern` to
      mean "every event") against a per rule+group_key river.anomaly
      online model (rain.modules.tickets.rules._ml_features), firing
      once its anomaly score clears `ml_score_threshold` and the group
      has seen at least `ml_warmup_count` events (so a freshly-created
      rule doesn't flag its own cold-start baseline). `ml_algorithm`
      picks which river.anomaly detector (see rules.ML_ALGORITHMS for
      the full set and why only three of river's six qualify -- the
      other three need a supervised target this app has no ground truth
      for). `group_by` (none|host|program) keeps a separate model per
      group-key value; `window_minutes` is this type's re-arm cooldown
      between fires for a given group -- unused by "single"/
      "repetition", which have no window concept at all. Per-group
      model state (and the running per-feature stats a firing event's
      "why" explanation is computed from) lives in TicketRuleState, not
      here.

    This table used to be two: TicketRule (single-event, "does this one
    event become a ticket") and a separate CorrelationRule (multi-event:
    a "threshold" type counting N matches in a trailing window, or this
    same ml_anomaly logic) evaluated independently alongside it. The
    "threshold" type was dropped outright rather than folded in here --
    it duplicated what "repetition" already does more simply (one open
    ticket accumulating repeat occurrences, flagged problematic, instead
    of a fresh aggregated ticket per window), so there was no reason to
    keep both. See migration 0038 for the consolidation.

    `ml_sidecar_enabled` (migration 0043): repetition and ML anomaly
    detection aren't really competing concerns the way the three
    promotion_type tabs make them look -- repetition decides whether an
    event folds into an open ticket or starts a new one, while anomaly
    detection is an orthogonal statistical layer that can just as well
    watch the same population repetition is tracking. Rather than force
    every repetition rule to also configure the full ML settings, this
    is one opt-in checkbox (defaulting on for a newly created repetition
    rule, at the form level -- this column's own server_default stays
    False so no existing rule silently starts scoring events), reusing
    whichever ml_algorithm/group_by/window_minutes/ml_score_threshold/
    ml_warmup_count values this same row already holds. A fired anomaly
    becomes a comment on whatever ticket repetition already touched,
    never a second ticket -- see rules._annotate_if_anomalous. Ignored
    entirely by "single"/"ml_anomaly" rules."""

    __tablename__ = "ticket_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    promotion_type: Mapped[str] = mapped_column(String(15), default="single", server_default="single")
    ticket_type: Mapped[str] = mapped_column(String(15))  # incident | vulnerability | change
    match_field: Mapped[str] = mapped_column(String(15), default="message", server_default="message")  # message|host|program
    pattern: Mapped[str] = mapped_column(String(500))
    title_template: Mapped[str] = mapped_column(String(255), default="{message}", server_default="{message}")
    severity: Mapped[str] = mapped_column(String(15), default="medium", server_default="medium")
    asset_match_field: Mapped[str | None] = mapped_column(String(15), nullable=True)  # host|program, matched to Asset.external_id
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # ml_anomaly only -- ignored by "single"/"repetition" rules.
    group_by: Mapped[str] = mapped_column(String(15), default="none", server_default="none")  # none|host|program
    window_minutes: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    ml_score_threshold: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    ml_warmup_count: Mapped[int] = mapped_column(Integer, default=250, server_default="250")
    ml_algorithm: Mapped[str] = mapped_column(String(20), default="half_space_trees", server_default="half_space_trees")
    # repetition only -- ignored by "single"/"ml_anomaly" rules. See this
    # class's own docstring.
    ml_sidecar_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # ticket_type == "change" only -- ignored otherwise. See this class's
    # own docstring for the start_date/end_date default that comes with
    # it regardless of whether this is set.
    approval_flow_id: Mapped[int | None] = mapped_column(
        ForeignKey("approval_flows.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketRuleState(TenantBase):
    """One row per (rule, group-key) that's actually been scored -- an
    "ml_anomaly" rule, or a "repetition" rule with ml_sidecar_enabled
    (see TicketRule's own docstring) -- e.g. one row per host for a rule
    grouped by host. A plain "single" rule, or a "repetition" one with
    the sidecar off, never touches this table; neither has any
    window/cooldown concept or per-group model to persist.

    `ml_model` is a pickled river.anomaly detector (whichever the rule's
    own `ml_algorithm` names, see TicketRule's own docstring) and
    `ml_event_count` is how many events it's been fed, checked against
    the rule's ml_warmup_count. `last_triggered_at` tracks when this
    group last fired a ticket, so a model that keeps scoring above
    threshold doesn't spawn a new one on every subsequent matching
    event -- it re-arms once window_minutes has elapsed since the last
    trigger; null until the group's first fire (or simply while still
    warming up). Only rain.modules.tickets.rules ever writes ml_model,
    and only with bytes it just produced by pickling its own in-memory
    model -- never with anything read from a request -- so unpickling it
    back here doesn't cross a trust boundary the way unpickling arbitrary
    user input would.

    `ml_feature_stats` is a plain-JSON running mean/variance per feature
    (Welford's online algorithm -- {"severity": {"n":, "mean":, "m2":},
    ...}), updated alongside the model on every scored event. It's what
    lets a firing event get a one-line "why" (which feature deviated
    most, and by how many standard deviations) baked into the ticket's
    own description at creation time, instead of just a bare score --
    see rules._fire_ml. Plain JSON rather than pickling river.stats
    objects into ml_model itself: one fewer moving part, and directly
    inspectable if ever queried by hand. Null until this group's first
    scored event.

    `group_key` is `""` (never NULL) for an ungrouped (group_by="none")
    rule -- Postgres unique constraints treat every NULL as distinct from
    every other NULL, which would silently defeat both the uniqueness
    guarantee and the ON CONFLICT upsert in rain.modules.tickets.rules
    for any rule that isn't grouped."""

    __tablename__ = "ticket_rule_states"
    __table_args__ = (UniqueConstraint("rule_id", "group_key", name="uq_ticket_rule_states_rule_group"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("ticket_rules.id", ondelete="CASCADE"), index=True)
    group_key: Mapped[str] = mapped_column(String(255), default="", server_default="")
    last_triggered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ml_model: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ml_event_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ml_feature_stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Group(TenantBase):
    """A named set of users, scoped to this tenant -- the assignment target
    for an approval flow step (rather than naming individual people one by
    one every time a flow is defined)."""

    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("name", name="uq_groups_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # local | ldap -- an LDAP sync run only ever creates/updates/deletes
    # groups it owns (source == "ldap" and matching ldap_dn), so a
    # manually created group is never touched by it even if the names
    # happen to collide.
    source: Mapped[str] = mapped_column(String(15), default="local", server_default="local")
    ldap_dn: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["GroupMembership"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class GroupMembership(TenantBase):
    __tablename__ = "group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_memberships_group_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    # control.users id -- cross-schema, plain integer (see module docstring).
    user_id: Mapped[int] = mapped_column(Integer)

    group: Mapped[Group] = relationship(back_populates="members")


class ApprovalFlow(TenantBase):
    """A reusable, named approval process -- an ordered list of steps, each
    assigned to a group or an individual user. Change tickets attach one
    instance of a flow (ChangeApproval) at creation time; editing a flow
    afterwards doesn't retroactively change tickets already using it (each
    decision snapshots its step's label -- see ChangeApprovalDecision)."""

    __tablename__ = "approval_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Opt-in, per-flow -- not every Change process wants a syslog event
    # firing on approval, so this doesn't default on. When set, a Change
    # ticket running this flow gets a synthetic SyslogEvent the moment its
    # last approval step clears (see rain.modules.tickets.service.
    # decide_approval_step), which then flows through the same ticket-rule
    # and correlation-rule pipeline as any real inbound syslog line --
    # same convention rain.modules.documents.service's alert_on_change
    # already uses for a document's webhook-detected content change.
    notify_syslog_on_approval: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    steps: Mapped[list["ApprovalFlowStep"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", order_by="ApprovalFlowStep.sort_order"
    )


class ApprovalFlowStep(TenantBase):
    """One step in an ApprovalFlow. Exactly one of approver_group_id /
    approver_user_id is set (enforced at the app layer, not the DB, matching
    this codebase's light-touch constraint style elsewhere) -- a group step
    clears when any one of its members approves."""

    __tablename__ = "approval_flow_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("approval_flows.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    label: Mapped[str] = mapped_column(String(255))
    approver_group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    # control.users id -- cross-schema, plain integer (see module docstring).
    approver_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    flow: Mapped[ApprovalFlow] = relationship(back_populates="steps")
    approver_group: Mapped[Group | None] = relationship()


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
    ticket_number: Mapped[str] = mapped_column(String(31), unique=True, index=True)  # INC-000123 / VULN-000045 / CHG-000012
    ticket_type: Mapped[str] = mapped_column(String(15))  # incident | vulnerability | change
    # 500, not 255 -- see migration 0034. Syslog-promoted titles (built from
    # an event's message via a rule's title_template) routinely ran past
    # the old limit and got silently truncated in service.create_ticket.
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="open", server_default="open")
    severity: Mapped[str] = mapped_column(String(15), default="medium", server_default="medium")
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("syslog_events.id", ondelete="SET NULL"), nullable=True)
    # The Event Promotion Policy that produced this ticket, if any -- one
    # column for all three promotion_type values (a single, dedicated
    # source_correlation_rule_id existed here before migration 0038
    # unified TicketRule/CorrelationRule into one table; see TicketRule's
    # own docstring).
    source_rule_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_rules.id", ondelete="SET NULL"), nullable=True)
    # Set when this ticket was promoted from another one (incident/vulnerability
    # -> change is the only path today, but this is generic). SET NULL on
    # delete rather than CASCADE -- losing the origin ticket shouldn't take
    # the promoted one down with it.
    source_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    # Set when this ticket was produced by submitting a Service Catalog
    # form (rain.modules.catalog) -- SET NULL rather than blocking/cascading
    # deletion of the catalog item so a request already filed keeps
    # existing regardless of what happens to the catalog entry afterward.
    source_catalog_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_catalog_items.id", ondelete="SET NULL"), nullable=True
    )
    # change tickets only -- the maintenance/implementation window, with a
    # time of day (not just a day -- <input type="datetime-local">).
    # Shown on the tenant calendar alongside CalendarEntry rows, which
    # only need the .date() half of these for its day-grid placement.
    start_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Manually set (tickets list quick-action menu) to flag a recurring
    # problem -- conventionally, one that's happened more than 5 times in
    # the trailing 30 days -- rather than a one-off. Not auto-computed:
    # nothing in this schema groups "the same underlying issue" across
    # tickets closely enough to count occurrences without a real risk of
    # false positives (title text and asset alone both under- and
    # over-match in practice), so this stays a human judgment call.
    is_problematic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    assignee_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reporter_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Set when this ticket was filed through the public incident portal
    # (rain.modules.portal) by a visitor with no session at all --
    # reporter_user_id stays null the same as any other unattributed
    # ticket, but "Reported by" needs to say something more specific than
    # "-" for this one case. Never true at the same time reporter_user_id
    # is set (a signed-in portal submission attributes normally).
    reported_anonymously: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # DB-generated (GENERATED ALWAYS AS ... STORED, see migration 0023) from
    # ticket_number/title/description -- never written from Python, only
    # ever read (search_vector.op("@@")(...)), see rain.modules.search.
    # server_default=FetchedValue() (not a real DEFAULT clause -- Postgres
    # already refuses one on a generated column) tells SQLAlchemy this
    # column is populated by the server and must never be included in an
    # INSERT/UPDATE it emits; without it, a plain INSERT (e.g. creating a
    # ticket) fails with asyncpg.exceptions.GeneratedAlwaysError ("cannot
    # insert a non-DEFAULT value into column 'search_vector'") since
    # SQLAlchemy has no other way to know this attribute is generated
    # rather than an ordinary nullable column -- confirmed via a real
    # request once documents/tickets could be created again after 0023.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True, deferred=True, server_default=FetchedValue())
    if ENABLE_PGVECTOR:
        # Reserved for a future semantic-search source -- see
        # EMBEDDING_DIM's comment above. Always NULL today.
        embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    asset: Mapped[Asset | None] = relationship()
    source_rule: Mapped["TicketRule | None"] = relationship()
    source_ticket: Mapped["Ticket | None"] = relationship(remote_side=[id])
    source_catalog_item: Mapped["ServiceCatalogItem | None"] = relationship()
    comments: Mapped[list["TicketComment"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    status_changes: Mapped[list["TicketStatusChange"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketStatusChange.created_at"
    )
    assignment_changes: Mapped[list["TicketAssignmentChange"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketAssignmentChange.created_at"
    )
    asset_changes: Mapped[list["TicketAssetChange"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketAssetChange.created_at"
    )
    field_changes: Mapped[list["TicketFieldChange"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketFieldChange.created_at"
    )
    rule_triggers: Mapped[list["PlatformEventTrigger"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="PlatformEventTrigger.created_at"
    )
    approval: Mapped["ChangeApproval | None"] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", uselist=False
    )
    watchers: Mapped[list["TicketWatcher"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    field_values: Mapped[list["TicketFieldValue"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class TicketFieldValue(TenantBase):
    """EAV storage for a ticket's custom field values -- same shape as
    AssetFieldValue, just against a Ticket instead of an Asset. `field`
    is always a scope="ticket" CustomField row (see that model's own
    docstring); nothing here enforces that at the DB layer, the same
    trust boundary AssetFieldValue.field already has for scope="asset"."""

    __tablename__ = "ticket_field_values"
    __table_args__ = (UniqueConstraint("ticket_id", "field_id", name="uq_ticket_field_values"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_fields.id", ondelete="CASCADE"))
    value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="field_values")
    field: Mapped[CustomField] = relationship()


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


class TicketAssignmentChange(TenantBase):
    """Audit trail entry for an assignee change -- shown interleaved with
    comments and status changes in the ticket detail activity feed.
    `from_assignee_user_id` is null when the ticket had no assignee yet;
    `to_assignee_user_id` is null when a ticket is unassigned."""

    __tablename__ = "ticket_assignment_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_assignee_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_assignee_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="assignment_changes")


class TicketAssetChange(TenantBase):
    """Audit trail entry for a change to a ticket's affected asset -- shown
    interleaved with comments/status/assignment changes in the ticket detail
    activity feed. `from_asset_id`/`to_asset_id` are null when the ticket had
    no asset set / is being cleared, respectively."""

    __tablename__ = "ticket_asset_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    to_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="asset_changes")


class TicketFieldChange(TenantBase):
    """Generic audit trail entry for a simple field edit (severity,
    is_problematic, title) that doesn't warrant its own dedicated table
    the way status/assignee/asset changes do -- one row per edit, shown
    interleaved in the activity feed as a single "Date - Actor - Changed
    <field> from A to B" line, matching those other change kinds'
    formatting exactly (severity's A/B render as colored pills there,
    same as a status change's). field_name is one of "severity",
    "is_problematic", "title"."""

    __tablename__ = "ticket_field_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_name: Mapped[str] = mapped_column(String(30))
    from_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="field_changes")


class TicketWatcher(TenantBase):
    """Someone who gets emailed on a ticket's activity (new comments,
    status changes) beyond whoever's actively working it -- either a
    system user (`user_id`, a control.users id) or a bare `email` for
    someone with no account at all (e.g. an external stakeholder added
    via a Platform Response Rule's "Add a watcher" action). Exactly one
    of the two is ever set, enforced by uq_ticket_watchers_ticket_user_ci
    /uq_ticket_watchers_ticket_email below (email uniqueness is
    case-insensitive) rather than a CHECK constraint, since Postgres
    can't express "exactly one of two nullable columns" as a single
    UNIQUE index the way it can for each column on its own.

    A user gets a row here from three places: toggling "Watch" on the
    ticket detail page themselves, being the ticket's reporter (added
    automatically on creation, unless reported anonymously) or its
    assignee (added automatically whenever one is set) -- see
    rain.modules.tickets.service's create_ticket/update_assignee -- or a
    Platform Response Rule's "Add a watcher" action. Silent no-op if
    SMTP isn't configured, same as every other notification path (see
    notifications.py's module docstring).

    Email uniqueness (case-insensitive, per ticket) is enforced by a
    partial functional unique index created directly in its migration
    rather than declared here -- not something a plain declarative
    UniqueConstraint/Index in __table_args__ can express cleanly."""

    __tablename__ = "ticket_watchers"
    __table_args__ = (UniqueConstraint("ticket_id", "user_id", name="uq_ticket_watchers_ticket_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    # control.users id -- cross-schema, plain integer (see module docstring).
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[Ticket] = relationship(back_populates="watchers")


class ChangeApproval(TenantBase):
    """One change ticket's approval lifecycle -- which flow it's running
    (null if none was configured/selected), which step it's currently
    waiting on, and the running outcome. `current_step_order` matches an
    ApprovalFlowStep.sort_order; once the last step's decision is recorded,
    overall_status flips to "approved" (or "rejected" immediately, on any
    step's rejection -- rejection short-circuits the remaining steps)."""

    __tablename__ = "change_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), unique=True, index=True)
    flow_id: Mapped[int | None] = mapped_column(ForeignKey("approval_flows.id", ondelete="SET NULL"), nullable=True)
    current_step_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    overall_status: Mapped[str] = mapped_column(String(15), default="pending", server_default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="approval")
    flow: Mapped[ApprovalFlow | None] = relationship()
    decisions: Mapped[list["ChangeApprovalDecision"]] = relationship(
        back_populates="approval", cascade="all, delete-orphan", order_by="ChangeApprovalDecision.created_at"
    )


class ChangeApprovalDecision(TenantBase):
    """One approve/reject decision recorded against a ChangeApproval --
    the audit trail shown in the ticket's activity feed. step_label is a
    snapshot (not a live join to ApprovalFlowStep) so editing or deleting
    the flow template later doesn't rewrite what already happened."""

    __tablename__ = "change_approval_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("change_approvals.id", ondelete="CASCADE"), index=True)
    step_order: Mapped[int] = mapped_column(Integer)
    step_label: Mapped[str] = mapped_column(String(255))
    decided_by_user_id: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(15))  # approved | rejected
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    approval: Mapped[ChangeApproval] = relationship(back_populates="decisions")


class NotificationChannel(TenantBase):
    """email | slack | webhook. Config is Fernet-encrypted at rest via
    rain.core.crypto -- a recipient list for email, an incoming-webhook
    URL for slack, or (like Platform Response Rules' own "webhook" action)
    a `{"webhook_id": <WebhookConfig.id>}` reference for webhook, reusing
    the same centrally-configured webhook instead of a third place to
    enter a URL/payload/timeout. The SMTP relay itself is instance-wide
    (control.global_config, set by internal_admin) -- this table only
    holds who gets notified for this tenant and through which channel.

    message_template/subject_template (subject is email-only) are plain
    text with the same double-brace ({{ticket_number}}, {{title}}, ...)
    placeholder substitution as WebhookConfig.payload_template -- see
    rain.modules.tickets.notifications.render_template. Meaningless for
    webhook: that channel type's payload is the referenced WebhookConfig's
    own payload_template instead, not this field.

    No longer carries notify_on_incident/notify_on_vulnerability: those
    drove an unconditional "notify on every ticket of this type" firing
    that ran in parallel with (and was a strict subset of) Platform Event
    rules -- a rule with an action pointed at this channel and pattern
    ".*" covers the same case, explicitly and visibly, so the always-on
    duplicate was removed rather than kept as a second code path (see
    migration 0006)."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_type: Mapped[str] = mapped_column(String(15))  # email | slack | webhook
    name: Mapped[str] = mapped_column(String(255))
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    message_template: Mapped[str] = mapped_column(Text, default="", server_default="")
    subject_template: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookConfig(TenantBase):
    """A centrally-configured outbound webhook -- one definition (Admin >
    Webhooks), referenced by id from anywhere that needs to call one
    instead of each place inlining its own URL/headers/payload/timeout:
    Platform Response Rules' "webhook" action, and a Document's
    "populate from webhook" setting. payload_template uses the same
    double-brace ({{key}}) placeholder substitution either caller fills
    in with its own context (ticket fields, or nothing, for a document
    refresh) -- it's ignored for GET, which has no body."""

    __tablename__ = "webhook_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048))
    http_method: Mapped[str] = mapped_column(String(10), default="POST", server_default="POST")
    headers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    payload_template: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    # Comma-separated list of HTTP status codes that count as success, e.g.
    # "200,201,204" -- a plain string rather than an int[] column so the
    # admin form is just one text input, not a dynamic add/remove list.
    success_codes: Mapped[str] = mapped_column(String(255), default="200,201,202,204", server_default="200,201,202,204")
    # Opt-in: emit a syslog event (through the same rule engine real syslog
    # traffic goes through) whenever a call to this webhook fails or times
    # out, from either caller -- off by default so a webhook that's
    # expected to occasionally error doesn't become noisy on its own.
    alert_on_failure: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # Populate-from-webhook (text/markdown documents only -- see
    # rain.modules.documents.textbody.body_kind): webhook_id is which
    # WebhookConfig to call on "Refresh from webhook"; alert_on_change
    # opts into emitting a syslog event (through the same rule engine
    # real syslog traffic goes through) when a refresh's content differs
    # from what was stored, so it's optional rather than every refresh
    # being noisy.
    webhook_id: Mapped[int | None] = mapped_column(ForeignKey("webhook_configs.id", ondelete="SET NULL"), nullable=True)
    alert_on_change: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_refreshed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Opt-in JSON handling for a webhook response, evaluated by
    # rain.modules.documents.service.refresh_from_webhook: parse the
    # response body as JSON, then either pull one value out of it via
    # webhook_json_path (a JSONPath, same expression language/library as
    # ServiceCatalogField.source_expression's own "jsonpath" mode) or, with
    # no path set, save the whole parsed object pretty-printed. Invalid
    # JSON never fails the refresh -- it just falls back to saving the raw
    # response verbatim, same as webhook_response_is_json being off.
    webhook_response_is_json: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    webhook_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Opt-in (see migration 0046): calls the configured webhook again
    # every time this document's content is actually rendered for
    # someone to read, not just on the manual "Refresh from webhook"
    # button -- both of the places that happen (the document's own
    # detail page, rain.modules.documents.router.document_detail; and
    # Home, rain.modules.home.router.home, if this document is also
    # show_on_landing_page) call the same refresh_from_webhook, so a
    # successful call shows the freshly-fetched copy and a failed one
    # silently falls back to whatever's already stored (refresh_from_
    # webhook never writes on failure). Only does anything once webhook_id
    # above is actually set.
    refresh_on_view: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Optional, freeform -- a plain array rather than a normalized tags
    # table (see migration 0039's own docstring for why: nothing here
    # needs a tenant-wide tag registry or tag-scoped browsing, just
    # tagging a document and finding it by that tag later, and the
    # array feeds directly into search_vector below, which a join
    # table's GENERATED expression couldn't reference). Never NULL --
    # "no tags" is an empty array, not a null one, so callers can always
    # iterate it without a None-check.
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")
    # Opt-in (see migration 0042): exposed through the client portal's
    # "Shareable documents" tab (rain.modules.portal.router.portal_form)
    # to every visitor, including one with no session at all, even on a
    # tenant that otherwise requires an account for the rest of the
    # portal (portal_require_auth) -- the whole point of a tenant-
    # renamable "Trust Center"-style tab is that it stays reachable
    # without logging in. Off by default; unrelated to tags/search_vector.
    is_shareable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Opt-in (see migration 0045): this document's contents (rendered
    # Markdown, or plain text for a non-Markdown text file -- see
    # rain.modules.documents.textbody.body_kind) show up on the landing
    # page (rain.modules.home). More than one document can be flagged;
    # the landing page renders every flagged one, falling back to a
    # plain "Welcome to <instance>" only when none are. Off by default,
    # and independent of is_shareable above -- a document can be one,
    # the other, both, or neither.
    show_on_landing_page: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # DB-generated (GENERATED ALWAYS AS ... STORED, see migrations 0023
    # and 0039) from doc_number/title/tags/description -- never written
    # from Python, only ever read (search_vector.op("@@")(...)), see
    # rain.modules.search. Indexes metadata only, not the file body --
    # see that module's docstring. server_default=FetchedValue(): see
    # Ticket.search_vector's comment -- without it, creating a document
    # fails the same way creating a ticket did
    # (asyncpg.exceptions.GeneratedAlwaysError).
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True, deferred=True, server_default=FetchedValue())
    if ENABLE_PGVECTOR:
        # Reserved for a future semantic-search source -- see
        # EMBEDDING_DIM's comment near the top of this file. Always NULL
        # today.
        embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    links: Mapped[list["DocumentLink"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    webhook: Mapped["WebhookConfig | None"] = relationship()


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


class ServiceCatalogItem(TenantBase):
    """One requestable "service" in the tenant's self-service catalog
    (e.g. "Provision a new user", "Request VPN access") -- rendered as a
    form on /catalog (main app, under Records Authority) and the customer
    portal's Catalog tab. Submitting it creates a ticket of ticket_type
    whose description is the submitted answers serialized per
    payload_format (see ServiceCatalogField and rain.modules.catalog.
    service.render_payload). Optionally routed through an ApprovalFlow at
    submission time -- the same ChangeApproval/ApprovalFlow machinery
    Change tickets use, generalized here to any ticket_type (see
    rain.modules.tickets.service.start_approval, already generic over
    "the thing being approved")."""

    __tablename__ = "service_catalog_items"
    __table_args__ = (UniqueConstraint("key", name="uq_service_catalog_items_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(63), nullable=True)
    # incident | vulnerability | change -- rain.modules.tickets.schemas.TICKET_TYPES.
    ticket_type: Mapped[str] = mapped_column(String(15), default="incident", server_default="incident")
    default_severity: Mapped[str] = mapped_column(String(15), default="medium", server_default="medium")
    # json | kv -- how a submission's answers are serialized into the
    # created ticket's description (rain.modules.catalog.service.render_payload).
    payload_format: Mapped[str] = mapped_column(String(7), default="json", server_default="json")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    approval_flow_id: Mapped[int | None] = mapped_column(ForeignKey("approval_flows.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    approval_flow: Mapped[ApprovalFlow | None] = relationship()
    fields: Mapped[list["ServiceCatalogField"]] = relationship(
        back_populates="catalog_item", cascade="all, delete-orphan", order_by="ServiceCatalogField.sort_order"
    )


class ServiceCatalogField(TenantBase):
    """One question on a ServiceCatalogItem's form -- up to 10 per item
    (enforced at the app layer, rain.modules.catalog.router/service, same
    "cap enforced above the DB" trade-off as _MAX_APPROVAL_STEPS).
    field_key becomes both the submitted form field's name and the
    key/name used in the produced ticket's JSON/key=value payload, so it
    doubles as the machine-readable name the resulting ticket exposes,
    not just a UI label.

    A field can optionally pull its value from an existing Document
    instead of (or as a starting/fallback point for) free-form entry --
    source_mode "content" uses the document's whole text body (each line
    becomes an option, for a select field); "regex" evaluates
    source_expression (Python re, MULTILINE -- ^/$ anchor per line) against that body,
    taking each match's first capturing group if the pattern has one,
    else the whole match; "jsonpath" parses the body as JSON and
    evaluates source_expression as a JSONPath. A select field gets every
    match/result as its option list (falling back to select_options if
    that comes up empty); any other field type gets the first one as a
    prefilled but still-editable default. See rain.modules.catalog.
    service.resolve_field_source, also used by the admin form's live
    Preview button before a field is ever saved."""

    __tablename__ = "service_catalog_fields"
    __table_args__ = (UniqueConstraint("catalog_item_id", "field_key", name="uq_service_catalog_fields_item_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_item_id: Mapped[int] = mapped_column(ForeignKey("service_catalog_items.id", ondelete="CASCADE"), index=True)
    field_key: Mapped[str] = mapped_column(String(63))
    label: Mapped[str] = mapped_column(String(255))
    # text | number | boolean | date | url | email | select -- same set as
    # rain.modules.assets.schemas.FieldType, reused rather than duplicated.
    field_type: Mapped[str] = mapped_column(String(15), default="text", server_default="text")
    select_options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    # content | regex | jsonpath -- null means "not document-sourced", the
    # plain static field described above.
    source_mode: Mapped[str | None] = mapped_column(String(15), nullable=True)
    # The regex pattern or JSONPath expression; unused (and ignored) for
    # source_mode "content".
    source_expression: Mapped[str | None] = mapped_column(Text, nullable=True)

    catalog_item: Mapped[ServiceCatalogItem] = relationship(back_populates="fields")
    source_document: Mapped[Document | None] = relationship()


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
      mark_problematic              -> {} (no config)
      add_watcher                    -> {"email": str} or {"user_id": int} -- exactly one
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
    calendar entries usable as Event Promotion Policy triggers: when an occurrence
    falls due, the worker synthesizes a SyslogEvent exactly as if it had
    arrived over the wire (rain.modules.calendar.sweep), so the *existing*
    rule engine (TicketRule/Platform Events) reacts to it with no separate
    calendar-specific rule system needed. `last_fired_date` is the sweep's
    own dedup marker (one synthetic event per occurrence, not one per
    sweep tick).

    `document_id` (optional) is a plain "this entry is about this
    document" link -- what backs a document's own Calendar tab
    (rain.modules.documents.router.document_detail) and the entry form's
    "Related document" picker, e.g. "this document is due for revision
    every quarter." ON DELETE CASCADE: a revision reminder for a deleted
    document has no reason to survive as an orphan (same choice
    DocumentLink.document_id already made). Independent of `policy_ref`
    below -- linking an entry to a document here doesn't imply any
    auto-update action, it's purely a manual reminder unless `policy_ref`
    also opts into one.

    `policy_ref` is an opaque JSON blob carrying an occurrence-driven
    "policy" for this entry, round-tripping through .ics export/import
    (as a custom X-RAIN-POLICY property). The one shape acted on today
    (rain.modules.calendar.sweep) is `{"type": "refresh_document",
    "document_id": <id>}` -- refresh that document from its configured
    webhook (rain.modules.documents.service.refresh_from_webhook) on
    every due occurrence, e.g. "update document X quarterly" for real
    rather than just being reminded to. Its own document_id and this
    row's `document_id` column point at the same document in practice
    (the entry form only ever sets policy_ref for whichever document
    `document_id` already names -- see rain.modules.calendar.router),
    but they're read independently: `document_id` is what a plain
    reminder needs, `policy_ref` is what the sweep needs, and a document
    a tenant simply wants reminded about was never required to have a
    webhook configured at all. Independent of `emit_syslog_event` too;
    an entry can do any combination of the three."""

    __tablename__ = "calendar_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[dt.date] = mapped_column(Date)
    # null|daily|weekly|monthly|quarterly|biannual|annual -- see
    # rain.modules.calendar.recurrence.RECURRENCE_PRESETS
    recurrence: Mapped[str | None] = mapped_column(String(15), nullable=True)
    recurrence_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    emit_syslog_event: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    event_program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    policy_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_fired_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document | None] = relationship()


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
