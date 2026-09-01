# Database schema

A quick-reference map of every table RAIN defines: what it's for, its
columns, and how it relates to the rest. This is a snapshot, not the
source of truth -- the actual schema lives in two places, and this doc
should always agree with both:

- **Models**: `backend/src/rain/db/control_models.py` (the `control`
  schema, platform-wide) and `backend/src/rain/db/tenant_models.py`
  (the tenant schema, applied once per tenant). Every table's own
  docstring there explains the *why*; this doc is the *what*, for
  looking a table up without reading the whole file.
- **Migrations**: `backend/migrations/control/versions/` (10, as of
  this writing) and `backend/migrations/tenant/versions/` (47) --
  Alembic, one linear chain per schema kind. A tenant schema migrates
  independently of `control`, and every tenant schema migrates
  independently of every other one (see `docs/architecture.md`'s own
  "Migrations" section for how that's kept in sync at startup).

If you change a model, add a migration in the matching chain and
update this doc in the same change -- see `docs/code-layout.md` for
the full "how to add a change" walkthrough.

## Multi-tenancy: two schema kinds

Postgres schema-per-tenant. One `control` schema (platform-wide: which
tenants exist, every user regardless of tenant, sessions, instance
branding) plus one `tenant_<slug>` schema per tenant (everything a
single organization's own data touches: tickets, assets, documents,
...) -- same table definitions, a fresh schema per tenant, selected at
request time via SQLAlchemy's `schema_translate_map` (see
`rain.db.base`). Postgres can't enforce a foreign key across schemas,
so a reference from a tenant table back into `control` (e.g. a
ticket's `assignee_user_id`, pointing at `control.users.id`) is a
plain integer, validated at the application layer instead -- called
out per-column below as "cross-schema" wherever it appears.

---

## `control` schema (platform-wide)

| Table | Purpose |
|---|---|
| `tenants` | One row per tenant: `slug` (URL/portal-facing), `name`, `schema_name` (the actual `tenant_<slug>` Postgres schema), `is_active`. |
| `roles` | RBAC roles -- seeded with exactly `internal_admin` and `client` (see Auth & RBAC below); a table, not a hardcoded enum, so finer-grained roles are an admin action later, not a migration. |
| `users` | Every user, any tenant, any role -- `tenant_id` NULL for `internal_admin` (cross-tenant), required for a `client`/`client_admin`. `auth_source` (`local`/`ldap`/`saml`) decides whether `password_hash` is meaningful; `ldap_dn` only set for `ldap`. |
| `sessions` | DB-backed session -- only a sha256 hash of the cookie token is stored, never the token itself. `active_tenant_id` is which tenant an `internal_admin` is currently viewing (irrelevant for a `client`/`client_admin`, pinned to their own tenant). |
| `password_reset_tokens` | Single-use, hour-lived "Forgot password?" tokens -- `local` auth_source users only. |
| `global_config` | Instance-wide runtime settings (instance name, accent color, logo path, font) -- key/value, JSONB value. Cached process-wide with `LISTEN`/`NOTIFY` invalidation (`rain.core.config_store`), unlike the per-tenant config table below. |
| `branding_assets` | Durable backup of the uploaded logo (Postgres-backed, so a container recreated with no persistent uploads volume doesn't lose it) -- only used when `S3_BUCKET` isn't set. |
| `auth_providers` | One row each for `local`/`ldap`/`saml`, seeded once. `config` is plain JSONB; `config_encrypted` (Fernet, `rain.core.crypto`) is where an actual secret -- the LDAP bind password -- lives. |
| `syslog_source_map` | Routes an incoming syslog event to a tenant by `host`/`program` pattern, evaluated in `sort_order`, first match wins -- has to live here since the tenant isn't known yet at that point. `action="discard"` drops a matching event before it's persisted anywhere (a noisy source's events never even reach a tenant). |
| `audit_log` | Platform-level events: tenant/user/role/branding changes. (A *different*, tenant-scoped `audit_log` table -- see below -- holds per-tenant asset changes.) |

## Tenant schema (one `tenant_<slug>` per tenant)

### Assets & custom fields

| Table | Purpose |
|---|---|
| `asset_types` | Tenant-defined asset categories (a server, a container, a contact, ...) -- no built-in types ship by default. `key`/`name`/`icon`/`sort_order`. |
| `custom_fields` | EAV field *definitions* -- `scope` (`asset`\|`ticket`) shares one table for both rather than duplicating the concept. `asset_type_id` NULL means "every asset type" for an asset-scoped field; always NULL for a ticket-scoped one (those are tenant-wide across all three ticket types, never per-type). `field_type`: text/number/boolean/date/url/email/select. |
| `assets` | One inventory item -- `ci_number` (`CI-000123`), `asset_type_id`, `name`, `external_id` (correlates to a syslog event's `host`, for auto-linking), `status`, `owner_user_id`/`created_by`/`updated_by` (cross-schema). |
| `asset_field_values` | EAV field *values* -- one row per `(asset_id, field_id)`, JSONB `value`. |
| `export_profiles` | A saved column/header/order preset for CSV/JSON export, shared by the Assets and Tickets export screens (`scope` distinguishes which). |

### Tenant configuration

| Table | Purpose |
|---|---|
| `tenant_config` | Per-tenant runtime settings -- key/value, JSONB value. Same shape as `control.global_config` but read fresh every time (no process-wide cache -- see `rain.core.tenant_config`'s own docstring for why that's fine here). Holds things like `event_retention_hours`, `default_page_size`, `escalate_button_label`, `app_custom_js`/`portal_custom_js`, the portal's own flags. |

### Syslog ingestion & Event Promotion Policies

| Table | Purpose |
|---|---|
| `syslog_events` | A received syslog line, already routed to this tenant. Rolling window (retention-swept) -- promote anything worth keeping into a `Ticket`; a promoted event's `promoted_ticket_id` points at the result. `message` is the parsed/summarized form (CEF/JSON/kv all recognized); `raw`/`parsed_fields` keep the rest. |
| `ticket_rules` | An Event Promotion Policy. `promotion_type` (`single`\|`repetition`\|`ml_anomaly`) picks the shape; a `change`-typed `single`/`repetition` rule can also carry `approval_flow_id` to auto-attach a flow. ML-specific columns (`group_by`, `window_minutes`, `ml_score_threshold`, `ml_warmup_count`, `ml_algorithm`, `ml_sidecar_enabled`) only apply to `ml_anomaly` rules, or a `repetition` rule with its sidecar on. |
| `ticket_rule_states` | One row per `(rule_id, group_key)` that's actually been scored by ML anomaly detection -- the pickled `river.anomaly` model (`ml_model`), how many events it's seen (`ml_event_count`, checked against `ml_warmup_count`), running per-feature mean/variance (`ml_feature_stats`), and `last_triggered_at` (the rearm cooldown). Untouched by a plain `single` rule, or a `repetition` rule with no sidecar. |

### Groups & approvals

| Table | Purpose |
|---|---|
| `groups` | A named set of users -- the assignment target for an approval step. `source` (`local`\|`ldap`) plus `ldap_dn` for one synced from a directory. |
| `group_memberships` | `(group_id, user_id)` -- `user_id` is cross-schema (`control.users.id`). |
| `approval_flows` | A reusable, ordered approval process. `is_default` marks the one pre-selected on the New Change form; `notify_syslog_on_approval` optionally fires a synthetic syslog event (through the normal rule engine) the moment the flow's last step clears. |
| `approval_flow_steps` | One step -- `approver_group_id` XOR `approver_user_id` (app-enforced), `sort_order`, `label`. |
| `change_approvals` | One ticket's approval instance -- which `flow_id` it's running (if any), `current_step_order`, `overall_status` (`pending`\|`approved`\|`rejected`). One-to-one with a `Ticket` via a unique `ticket_id`. |
| `change_approval_decisions` | One approve/reject decision -- `step_label` is a snapshot (editing the flow template later doesn't rewrite history), `decided_by_user_id` (cross-schema), optional `comment`. |

### Tickets

| Table | Purpose |
|---|---|
| `ticket_statuses` | Tenant-defined status set (`Open`, `In Progress`, ...) replacing a fixed enum -- `key`/`label`/`color`/`is_closed`/`is_active`/`sort_order`. `Ticket.status` stores `key` as a plain string, app-validated, not a real FK. |
| `tickets` | The record itself -- `ticket_number` (`INC-`/`VULN-`/`CHG-000123`), `ticket_type`, `title`, `description`, `status`, `severity`, `asset_id`, `source_event_id`/`source_rule_id`/`source_ticket_id`/`source_catalog_item_id` (where it came from, all nullable), `start_date`/`end_date` (change tickets' maintenance window), `is_problematic`, `assignee_user_id`/`reporter_user_id` (cross-schema), `reported_anonymously`, `closed_at`. `search_vector` is a `GENERATED ALWAYS AS ... STORED` `tsvector` (never written from Python). `embedding` (`pgvector`, dimension 1536) only exists when `ENABLE_PGVECTOR` is on -- unpopulated, nothing reads or writes it (see `docs/architecture.md`'s Search section). |
| `ticket_field_values` | EAV storage for a ticket's custom field values -- same shape as `asset_field_values`, always against a `scope="ticket"` `custom_fields` row. |
| `ticket_comments` | Plain-text activity feed comments -- `author_user_id` NULL for a system-posted one (root-cause analysis, an automatic notice). |
| `ticket_status_changes` | Audit trail: one row per status transition (`from_status` NULL for the very first). |
| `ticket_assignment_changes` | Audit trail: one row per assignee change. |
| `ticket_asset_changes` | Audit trail: one row per affected-asset change. |
| `ticket_field_changes` | Audit trail: one row per plain-field edit (`severity`, `is_problematic`, `title`) that doesn't warrant its own dedicated table. |
| `ticket_watchers` | Who gets emailed on new comments/status changes -- exactly one of `user_id` (cross-schema) or a bare `email` (for someone with no account) is set per row. |

### Notifications & webhooks

| Table | Purpose |
|---|---|
| `notification_channels` | A reusable Slack/email/webhook destination -- `config_encrypted` (Fernet) holds the recipient list/incoming-webhook URL/`{"webhook_id": ...}` reference depending on `channel_type`. `message_template`/`subject_template` support `{{placeholder}}` substitution. |
| `webhook_configs` | One centrally-configured outbound webhook definition (URL, method, headers, payload template, timeout, success codes, `alert_on_failure`) -- referenced by id from Platform Response Rules' webhook action, a document's "populate from webhook", and the escalation button. |

### Documents

| Table | Purpose |
|---|---|
| `documents` | A `DOC-xxxxxx` entry -- `storage_key` is an opaque identifier into whichever `StorageBackend` is active (local disk or S3), not a filesystem path. `webhook_id`/`alert_on_change`/`last_refreshed_at`/`webhook_response_is_json`/`webhook_json_path`/`refresh_on_view` back "populate from webhook". `tags` is a plain `text[]` (feeds `search_vector` directly). `is_shareable` (client portal) and `show_on_landing_page` (Home) are independent opt-in flags. `search_vector`/`embedding`: same shape as `tickets`' own. |
| `document_links` | Polymorphic link to an asset or a ticket -- `linked_type`/`linked_id` are app-validated (no real FK across two possible target tables). |

### Service Catalog

| Table | Purpose |
|---|---|
| `service_catalog_items` | One requestable "service" -- `ticket_type`/`default_severity` for what submitting it produces, `payload_format` (`json`\|`kv`) for how answers serialize into the ticket's description, optional `approval_flow_id`. |
| `service_catalog_fields` | Up to 10 questions per item (app-enforced cap). `source_mode` (`content`\|`regex`\|`jsonpath`, or NULL for a plain static field) plus `source_document_id`/`source_expression` let a field pull its value/options from an existing Document instead of free-form entry. |

### Platform Response Rules

| Table | Purpose |
|---|---|
| `platform_event_rules` | Reacts when a ticket lifecycle event happens (`trigger_event`: created/closed/change-approved, per type) and `pattern` matches `match_field`. Unlike `ticket_rules` (first match wins), every active matching rule fires here -- a reaction layer, not a routing decision. |
| `platform_event_actions` | One action per rule -- `action_type` (`notify_slack`\|`notify_email`\|`webhook`\|`attach_document`\|`attach_asset`\|`mark_problematic`\|`add_watcher`), `config` JSONB shaped per type. |
| `platform_event_triggers` | Audit trail: this rule fired for this ticket, with a human-readable `summary` of what each action did. `rule_name` is a snapshot; `rule_id` is `SET NULL` (not cascaded) on rule deletion so the log entry survives. |

### Calendar

| Table | Purpose |
|---|---|
| `calendar_entries` | One-off or recurring dated entries. `recurrence` (`daily`\|`weekly`\|`monthly`\|`quarterly`\|`biannual`\|`annual`\|NULL) -- occurrences computed on the fly (`rain.modules.calendar.recurrence`), never materialized as rows. `emit_syslog_event`/`event_program` bridge an occurrence into the normal rule engine; `document_id` links a reminder to a document; `policy_ref` (JSON) optionally makes an occurrence auto-refresh that document from its webhook. `last_fired_date` dedups the sweep. |

### Audit

| Table | Purpose |
|---|---|
| `audit_log` | Per-tenant change history for asset registry entities (a *different* table from `control.audit_log`, which is platform-level). |

---

## Conventions worth knowing before you add a table

- **Primary keys**: plain `Integer` autoincrement everywhere, no UUIDs.
- **Timestamps**: `DateTime(timezone=True)`, `server_default=func.now()`;
  an `updated_at` that should auto-touch also carries `onupdate=func.now()`.
- **Soft config, not enums**: a field like `Ticket.status`,
  `Ticket.ticket_type`, or `PlatformEventAction.action_type` is a plain
  `String`, validated at the application layer -- not a Postgres `ENUM`
  type, which would need a migration of its own to add a value. Search
  the relevant `rain.modules.*.schemas` module for the actual allowed
  set.
- **EAV for custom fields**: `custom_fields` (definitions) +
  `asset_field_values`/`ticket_field_values` (values), not a wide table
  with one column per possible field -- this is what lets a tenant
  define fields at runtime with no migration.
- **Audit trail per concern, not one big log**: tickets get several
  dedicated tables (`ticket_status_changes`, `ticket_assignment_changes`,
  ...) rather than one generic "field changed" table, so each kind can
  render its own activity-feed formatting (a status pill, an assignee
  name) without parsing a generic diff.
- **Cross-schema references are plain integers**: any tenant-schema
  column pointing at a `control` table (`assignee_user_id`,
  `approver_user_id`, `owner_user_id`, ...) is un-enforced at the DB
  layer -- Postgres can't FK across schemas. Called out per-column
  above; validate these at the application layer if you add one.
- **`GENERATED ALWAYS AS ... STORED` columns** (`search_vector` on
  `tickets`/`documents`) need `server_default=FetchedValue()` on the
  SQLAlchemy side or a plain `INSERT` fails -- see either column's own
  comment in the model file for exactly why.
