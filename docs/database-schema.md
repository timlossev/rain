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
- **Migrations**: `backend/migrations/control/versions/` (9, as of
  this writing) and `backend/migrations/tenant/versions/` (47) --
  Alembic, one linear chain per schema kind, numbered sequentially
  (`0001`, `0002`, ...) rather than Alembic's default random hex
  revision ids, so the chain doubles as a build-number history -- see
  "Migration history by number" below. A tenant schema migrates
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
| `users` | Every user, any tenant, any role -- `tenant_id` NULL for `internal_admin` (cross-tenant), required for a `client`/`client_admin`. `auth_source` (`local`/`ldap`/`saml`) decides whether `password_hash` is meaningful; `ldap_dn` only set for `ldap`. `last_login_at` (0010) is stamped by every successful sign-in, local/LDAP/SAML alike, from the one place all three converge (`rain.modules.auth.router._issue_session`) -- backs Admin > Users' "Last login" column/CSV export, the dormant-account evidence nothing here produced before. |
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
| `tickets` | The record itself -- `ticket_number` (`INC-`/`VULN-`/`CHG-000123`), `ticket_type`, `title`, `description`, `status`, `severity`, `asset_id`, `source_event_id`/`source_rule_id`/`source_ticket_id`/`source_catalog_item_id` (where it came from, all nullable), `start_date`/`end_date` (change tickets' maintenance window), `is_problematic`, `assignee_user_id`/`reporter_user_id` (cross-schema), `reported_anonymously`, `closed_at`, `external_finding_key` (0050, nullable, unique) -- an optional deterministic identity from a recurring external import (a vulnerability scan's own finding ID, typically), what the ticket importer's opt-in "Dedup key" mapping looks a row up by to create/leave-alone/reopen instead of always creating. `search_vector` is a `GENERATED ALWAYS AS ... STORED` `tsvector` (never written from Python). `embedding` (`pgvector`, dimension 1536) only exists when `ENABLE_PGVECTOR` is on -- unpopulated, nothing reads or writes it (see `docs/architecture.md`'s Search section). |
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
| `documents` | A `DOC-xxxxxx` entry -- `storage_key` is an opaque identifier into whichever `StorageBackend` is active (local disk or S3), not a filesystem path. `webhook_id`/`alert_on_change`/`last_refreshed_at`/`webhook_response_is_json`/`webhook_json_path`/`refresh_on_view` back "populate from webhook". `owner_user_id` (cross-schema) is who's currently responsible for keeping it current, reassignable, separate from `uploaded_by` (a one-time creation fact). `next_review_at` (0048, nullable `date`) flags "overdue for review" on the list once it passes -- independent of any calendar reminder. `ack_required_group_id`/`ack_required_user_id`/`ack_requested_at` (0049) are an optional "who must acknowledge this" assignment -- the same group-or-user shape `ApprovalFlowStep` uses for a change ticket's approvers -- with `ack_requested_at` marking when that requirement was last (re)issued, not just whether one exists. `tags` is a plain `text[]` (feeds `search_vector` directly). `is_shareable` (client portal) and `show_on_landing_page` (Home) are independent opt-in flags. `search_vector`/`embedding`: same shape as `tickets`' own. |
| `document_acknowledgments` | (0048) One row per (`document_id`, `user_id`) who has clicked "I have read this" on that document's Properties tab, upserted so `acknowledged_at` always reflects the latest read, not the first. `ON DELETE CASCADE` on `document_id`. `user_id` is the same unenforced cross-schema `control.users` id as `owner_user_id`/`uploaded_by`. |
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
| `platform_event_triggers` | Audit trail: this rule fired for this ticket (`ticket_id`) or, since 0049, this document (`document_id`) -- exactly one of the two set, both nullable now, same unenforced-at-the-DB convention as `ApprovalFlowStep`'s own group-or-user split -- with a human-readable `summary` of what each action did. `rule_name` is a snapshot; `rule_id` is `SET NULL` (not cascaded) on rule deletion so the log entry survives. |

### Calendar

| Table | Purpose |
|---|---|
| `calendar_entries` | One-off or recurring dated entries. `recurrence` (`daily`\|`weekly`\|`monthly`\|`quarterly`\|`biannual`\|`annual`\|NULL) -- occurrences computed on the fly (`rain.modules.calendar.recurrence`), never materialized as rows. `emit_syslog_event`/`event_program` bridge an occurrence into the normal rule engine; `document_id` links a reminder to a document; `policy_ref` (JSON) optionally makes an occurrence auto-refresh that document from its webhook. `last_fired_date` dedups the sweep. |

### Audit

| Table | Purpose |
|---|---|
| `audit_log` | Per-tenant change history for asset registry entities (a *different* table from `control.audit_log`, which is platform-level). |

---

## Migration history by number

Every table/column above traces back to one of these -- `alembic -n
tenant history` (or `-n control`) from `backend/` shows the same chain
straight from the DB. Numbers are per schema kind: tenant `0046` and
control `0009` are unrelated migrations that happen to share no
numbering, run independently, and land in different schemas.

### Tenant schema (`backend/migrations/tenant/versions/`)

| # | Change |
|---|---|
| 0001 | Initial schema: Asset Registry (`asset_types`, `custom_fields`, `assets`, `asset_field_values`, `export_profiles`). |
| 0002 | Ticketing: `syslog_events`, `ticket_rules`, `tickets`, `ticket_comments`, `notification_channels`. |
| 0003 | Document repository: `documents`, `document_links`. |
| 0004 | Platform Response Rules: `platform_event_rules`/`platform_event_actions`/`platform_event_triggers`. |
| 0005 | `ticket_statuses` -- per-tenant customizable statuses, seeded with the previous hardcoded open/in_progress/resolved/closed. |
| 0006 | Drop `notification_channels.notify_on_incident`/`notify_on_vulnerability`. |
| 0007 | `ticket_status_changes` audit trail. |
| 0008 | `calendar_entries` -- per-tenant calendar with recurring-entry presets. |
| 0009 | `documents.updated_at` (documents became editable in-place). |
| 0010 | `correlation_rules`/`correlation_rule_states` -- multi-event ("N matching events") rules; unified into `ticket_rules` at 0038. |
| 0011 | `ticket_assignment_changes` audit trail. |
| 0012 | `ticket_asset_changes` audit trail. |
| 0013 | Groups & approvals: `groups`, `approval_flows`, `approval_flow_steps`, `change_approvals`, `change_approval_decisions`. |
| 0014 | `chg_number_seq` -- ticket-number sequence for the "change" ticket type. |
| 0015 | `groups.source`/`ldap_dn` -- distinguishes an LDAP-synced group from a local one. |
| 0016 | `tickets.is_chronic` -- manually-set repeat-incident flag; renamed at 0027. |
| 0017 | `ticket_field_changes` -- generic audit trail for simple field edits. |
| 0018 | `export_profiles.scope` -- distinguishes an asset export profile from a ticket one. |
| 0019 | `tickets.start_date`/`end_date`: `DATE` -> `TIMESTAMPTZ`. |
| 0020 | `webhook_configs` -- centrally-configured outbound webhooks. |
| 0021 | `webhook_configs.alert_on_failure`. |
| 0022 | Drop the cloud-sync scaffolding (`sync_connections`, `sync_runs`). |
| 0023 | Search: `search_vector` generated `tsvector` columns + GIN indexes on `tickets`/`documents`. |
| 0024 | `notification_channels.message_template`/`subject_template`. |
| 0025 | `assets.ci_number` -- human-readable identifier (`CI-000123`). |
| 0026 | `tickets.reported_anonymously`. |
| 0027 | `tickets.is_chronic` -> `is_problematic` (rename). |
| 0028 | `ticket_watchers`. |
| 0029 | `correlation_rules` gains a second `rule_type`, `ml_anomaly`. |
| 0030 | `ticket_watchers.email` -- a watcher with no system account. |
| 0031 | `syslog_events.event_format` (`plain`\|`cef`\|`json`\|`kv`). |
| 0032 | Service Catalog: `service_catalog_items`, `service_catalog_fields`. |
| 0033 | `approval_flows.notify_syslog_on_approval`. |
| 0034 | `tickets.title`: widen `VARCHAR(255)` -> `VARCHAR(500)`. |
| 0035 | `ticket_rules.combine_by_title`. |
| 0036 | `documents.webhook_response_is_json`/`webhook_json_path`. |
| 0037 | `custom_fields.scope` + `ticket_field_values` -- custom fields on tickets, not just assets. |
| 0038 | Unify Event Promotion Policies and Correlation Rules into one `ticket_rules` table. |
| 0039 | `documents.tags`. |
| 0040 | `calendar_entries.document_id`. |
| 0041 | `ticket_rules.ml_algorithm` + per-rule-state feature stats. |
| 0042 | `documents.is_shareable`. |
| 0043 | `ticket_rules.ml_sidecar_enabled` -- ML scoring alongside a `repetition` rule. |
| 0044 | `ticket_rules.approval_flow_id`. |
| 0045 | `documents.show_on_landing_page`. |
| 0046 | `documents.refresh_on_view`. |
| 0047 | `documents.owner_user_id` -- who's responsible for keeping it current. |
| 0048 | `documents.next_review_at` + `document_acknowledgments` -- review-due tracking and read acknowledgment. |
| 0049 | `documents.ack_required_group_id`/`ack_required_user_id`/`ack_requested_at` -- an assignable, notified acknowledgment requirement; `platform_event_triggers.ticket_id` becomes nullable, gains `document_id` (Platform Response Rules now also react to a document pending acknowledgment). |
| 0050 | `tickets.external_finding_key` (nullable, unique) -- opt-in dedup identity for the ticket CSV/JSON importer's "Dedup key" mapping. |

### `control` schema (`backend/migrations/control/versions/`)

| # | Change |
|---|---|
| 0001 | Initial schema: `tenants`, `roles`, `users`, `sessions`, `global_config`, `auth_providers`, `syslog_source_map`, `audit_log`. |
| 0002 | `syslog_source_map` -- source-to-tenant routing table. |
| 0003 | LDAP auth provider: encrypted connection config + last-sync bookkeeping. |
| 0004 | `syslog_source_map.action` (`route`\|`discard`). |
| 0005 | Remove the seeded `oidc` `auth_providers` row -- SAML replaced it as the real SSO option. |
| 0006 | Enable the `pgvector` extension. |
| 0007 | `client_admin` role, pinned to one tenant like `client`. |
| 0008 | `password_reset_tokens` -- self-service "Forgot password?" for local auth. |
| 0009 | `branding_assets` -- durable backup of the branding logo. |
| 0010 | `users.last_login_at` -- stamped on every successful sign-in. |

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
