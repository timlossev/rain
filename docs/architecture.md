# RAIN architecture

This is the living design doc for RAIN, kept in-repo so future work extends
the same foundation rather than re-deriving it. See the repo root
[`README.md`](../README.md) for the quickstart,
[`database-schema.md`](database-schema.md) for every table, and
[`code-layout.md`](code-layout.md) for where things live in the
codebase and how to add to it.

## Containers

| Service | Image basis | Role |
|---|---|---|
| `caddy` | `caddy:2-alpine` | Reverse proxy + automatic HTTPS. Only container exposing 80/443. |
| `app` | `python:3.12-alpine`, multi-stage | FastAPI web app (Uvicorn), server-rendered UI. |
| `worker` | same image as `app`, different command | The syslog listener (TCP+UDP), rule engine, notifier, and retention sweeper -- see Ticketing below. Publishes its own port (`SYSLOG_PORT`, default 5514) directly, bypassing Caddy since this is raw syslog, not HTTP. Optional: `EMBED_WORKER=true` folds these same duties into the `app` container instead (see "Deployment shapes" below). |
| `db` | `pgvector/pgvector:pg17-trixie` (official image) | One Postgres instance; `control` schema plus one `tenant_<slug>` schema per tenant. Optional: `POSTGRES_URL` points at an external/managed Postgres instead. |

Only two inputs are needed outside the database: `POSTGRES_PASSWORD` and
`APP_SECRET_KEY` (session-cookie signing + the Fernet key that encrypts
config-at-rest, e.g. the SMTP relay password). `bootstrap.py` /
`bootstrap.ps1` / `bootstrap.sh` generate both into `.env` on first run,
and interactively ask (with a working-default fast path, and skipped
outright when run non-interactively) which of the deployment shapes
below to set up -- built-in vs external Postgres, tested live before
being saved, with an explicit override if the test fails; local disk
vs S3 document storage; separate `worker` vs `EMBED_WORKER=true`.
`RAIN_DOMAIN` is optional and defaults to `localhost` (Caddy's internal CA).
Everything else lives in Postgres and is edited at runtime through the
setup wizard and Admin UI.

### Deployment shapes

The default shape is four containers (`caddy`, `app`, `worker`, `db`),
each independently droppable via a Compose profile + one `.env` flag:
`local-db` (drop with `POSTGRES_URL` set), `web-frontend` (drop with
`WEB_FRONTEND=false`), `worker` (drop with `EMBED_WORKER=true`). Nothing
in the app code branches on "which shape am I" beyond reading the
relevant `Settings` field -- `rain.main`'s `lifespan` starts
`rain.worker_runtime.WorkerServices` (the same syslog-listener-plus-
background-loops object the standalone `rain-worker` process uses,
factored out specifically so both callers share it -- see that module's
own docstring) when `embed_worker` is true, and
`rain.modules.documents.storage.get_storage()` returns an
`S3StorageBackend` instead of a `LocalStorageBackend` when `s3_bucket`
is set. Neither of those two settings know about the other, or about
`POSTGRES_URL`/`WEB_FRONTEND` -- each is an independent axis, combinable
in any mix.

**Minimal mode** is all four axes flipped at once: `EMBED_WORKER=true`,
`POSTGRES_URL` set, `WEB_FRONTEND=false`, `S3_BUCKET` set, and
`COMPOSE_PROFILES=` (empty, dropping `local-db`/`web-frontend`/`worker`
all at once) -- one `app` container, no other RAIN-managed
infrastructure. Needs `docker-compose.minimal.yml` layered on top of the
base file too: the base `app` service doesn't publish `SYSLOG_PORT` by
default (it would conflict with the separate `worker` service's own
mapping of that same host port in the normal topology this mode isn't
running), so the overlay adds it back. Without `S3_BUCKET` set in this
mode, document bodies live in the container's own writable layer with no
volume behind it at all, gone the next time the container is recreated
-- an explicit, documented trade-off for genuine single-container simplicity,
not an oversight. Branding assets (the logo, and the client portal's
optional background image) don't share that fate either way: each is
always served from local disk (same as ever), but also always has a
durable backup to restore that local copy from at next startup -- S3
when `S3_BUCKET` is set, its own row in `control.branding_assets`
(Postgres, already required infrastructure) when it isn't. See
`rain.web.uploads`'s docstring.

**Kubernetes.** `charts/rain/` is a Helm chart covering the same two
shapes, translated onto the same underlying `Settings` fields (an
Ingress instead of Caddy, a `worker.embedded` value instead of
`EMBED_WORKER`/`COMPOSE_PROFILES`, `storage.s3.*`/`storage.persistence.*`
instead of `S3_BUCKET`/the `rain_uploads` volume) rather than a second,
independently-maintained deployment story -- see `charts/rain/README.md`.
Not installed against a real cluster as part of building it (none was
available); rendered and reviewed by hand against the exact env vars the
app expects instead.

## Multi-tenancy: schema-per-tenant

- `control` schema (always present): `tenants`, `users`, `sessions`,
  `roles`, `global_config`, `auth_providers`, `syslog_source_map`,
  `audit_log`.
- `tenant_<slug>` schema per tenant: `asset_types`, `custom_fields` (a
  `scope` column shared between asset- and ticket-scoped field
  definitions -- see below), `assets`, `asset_field_values`,
  `ticket_field_values`, `export_profiles`, `tenant_config`,
  `syslog_events`, `ticket_rules`, `tickets`, `ticket_comments`,
  `notification_channels`, `webhook_configs`, `documents`,
  `document_links`, `audit_log`.
- Postgres can't enforce foreign keys across schemas, so references back
  into `control` (e.g. `assets.owner_user_id`) are plain integers,
  validated at the application layer instead of the DB.

### Migrations

Two independent Alembic chains, driven from one `alembic.ini` via named
sections (`[control]` / `[tenant]`, selected with `Config(ini_section=...)`):

- `migrations/control/` -- applied once, to the `control` schema.
- `migrations/tenant/` -- the exact same revision history applied to every
  `tenant_<slug>` schema via SQLAlchemy's `schema_translate_map` recipe:
  tenant models declare no explicit schema, so `{None: "tenant_acme"}`
  redirects every table (and the `alembic_version` table itself, via
  `version_table_schema`) at execution time.

`rain.db.migrate` runs both programmatically (`upgrade_control_async`,
`upgrade_tenant_async`), always through `asyncio.to_thread` since Alembic's
`command.upgrade` blocks on its own internal `asyncio.run(...)`.
`rain.db.provisioning.provision_tenant()` creates the schema and brings it
to head; `reconcile_all_tenant_schemas()` runs at every app/worker startup
so a code upgrade that adds tenant tables doesn't need a manual per-tenant
step.

### Request-time tenant resolution

`rain.core.tenancy` resolves session → user → active tenant per request.
`client` users are pinned to their one tenant; `internal_admin` users carry
their current selection on the session row (the tenant switcher in Admin).
`get_tenant_db()` opens a session with `schema_translate_map={None: schema}`
applied, so route code queries `rain.db.tenant_models` normally and
transparently lands in the right tenant's schema.

## Auth & RBAC

Local email+password (Argon2, `argon2-cffi`), LDAP/Active Directory (bind
auth + periodic user/group sync, `rain.modules.auth.ldap_sync`), and SAML
2.0 SSO (`rain.modules.auth.saml_provider`, `python3-saml`) are all
functional, one `control.auth_providers` row each. Sessions are DB-backed
(`control.sessions`): the cookie holds an opaque token, only its sha256
hash is stored, revocation is a row delete. A local/LDAP user authenticates
through the password form (`rain.modules.auth.provider.authenticate_user`
dispatches on `User.auth_source`); SAML is a separate browser-redirect
flow entirely (`/auth/saml/login` → IdP → `/auth/saml/acs`) that mints the
same kind of session at the end instead of checking a password.

Self-service password reset (`/forgot-password`, `/reset-password`)
follows the same DB-backed-opaque-token shape as sessions:
`control.password_reset_tokens` stores only a token's sha256 hash,
single-use (`used_at`) and expiring after an hour. It's gated on an
SMTP relay being configured (`rain.modules.tickets.notifications.
send_email`, reused rather than duplicated) and only ever issued for
`auth_source == "local"` users -- LDAP/SAML accounts have no local
password to reset. Requesting a reset always returns the same response
regardless of whether the address matched an account, and completing
one deletes every `control.sessions` row for that user, signing them
out everywhere.

Roles come from a `control.roles` table (not a hardcoded enum), seeded with
`internal_admin` (platform operator, all tenants, every setting),
`client` (full control scoped to their own tenant, no admin functions),
and `client_admin` (pinned to one tenant exactly like `client` --
`CurrentUser.is_internal_admin` is false for both -- but also passes
`rain.core.rbac.require_admin`, giving them admin rights over that one
tenant's own tenant-scoped settings: Ticket Statuses, Notification
Channels, Groups, Approval Flows, Webhooks, Event Promotion Policies,
Platform Response Rules). `require_admin` accepts
`internal_admin` or `client_admin`; platform-wide settings (Branding,
Tenants, Users, Auth Providers, SMTP Relay, Syslog Listener) stay on the
stricter `require_internal_admin` instead. The tenant scoping itself
needs no extra filtering in the tenant-scoped routes: `get_tenant_db` is
already bound to the caller's one active tenant regardless of which of
the two roles is asking, so there's no query path there that could reach
another tenant's rows. The Admin nav mirrors this split into two
submenus, Platform Administration and Tenant Administration.

**API spec.** FastAPI's own `/docs`, `/redoc`, `/openapi.json` are
disabled (`docs_url=None` etc. on the `FastAPI()` constructor) and
replaced with equivalents behind `require_internal_admin` -- the
generated spec covers every route/parameter/response shape, which
shouldn't be world-readable to an unauthenticated caller any more than
any other platform-wide setting is. Linked from Admin > Platform
Administration > API Documentation. Every router registers a `tags=`
so the generated docs group by module (Tickets, Assets, Admin, Portal,
...) instead of listing every route flat. There's no separate JSON/
REST API for external integration -- this spec documents the same
server-rendered routes the web UI itself calls; Webhooks + Platform
Response Rules are the supported way to react to RAIN's events from
outside the app.

## Tree navigation

`rain.core.nav_registry` is a registry modules add nodes to at import time
(`NavNode(key=..., label=..., href=..., children=[...], children_provider=...)`).
The tree is resolved fresh per request (role-filtered, dynamic children
like Assets' "By Type" list resolved via `children_provider`) and handed to
`base.html`, which renders it recursively and lets plain JS handle
expand/collapse. This is the extension point Ticketing and Documents plug
into without touching the shell.

## Branding & runtime config

`control.global_config` is a typed key/value table, cached in-process
(`rain.core.config_store`) and kept fresh across the `app` and `worker`
processes via Postgres `LISTEN`/`NOTIFY` -- no Redis needed just for this.
Accent color and logo are instance-wide (set once by `internal_admin`, not
per-tenant white-labeling); the setup wizard captures them alongside the
first tenant and admin account.

## Why no Tailwind/htmx/Alpine

The plan called for a server-rendered UI with HTMX/Alpine + Tailwind. In
practice the UI's actual surface -- nav expand/collapse, reloading a
custom-fields fragment when the asset type changes, confirm-before-delete
-- is about 70 lines of vanilla JS, and the visual design is one hand-written
CSS file using custom properties for the accent color. Dropping the three
libraries removes an entire JS supply chain (nothing to download at image
build time, nothing to patch for CVEs, no version pinning to maintain) at
no real cost to the UI. If a later feature's interactions outgrow plain
`fetch()` calls, htmx is a single `<script>` tag away and nothing here
would need to change to adopt it. The one addition since, `static/js/live.js`,
follows the same rule: a plain `WebSocket` client with
no library, kept in its own file (loaded only on the live-viewer page via
`{% block extra_scripts %}`) rather than bloating the shared `app.js`.

## Asset Registry

- `asset_types` / `custom_fields` (EAV field definitions, `asset_type_id`
  nullable = applies to every type; `scope="asset"` here, `scope="ticket"`
  for the Ticketing section's own custom fields below -- one shared
  definitions table, filtered by scope at every call site) / `assets` /
  `asset_field_values`.
- CSV/JSON import: upload → column-to-field mapping (auto-suggested by
  header name) → commit, upserting by `external_id` when present
  (`rain.modules.assets.importer`).
- CSV/JSON export: ad-hoc or saved `export_profiles` -- pick columns,
  headers, and order (`rain.modules.assets.exporter`).

## Ticketing

**Ingestion.** `worker` runs a hand-written RFC 3164 / RFC 5424 syslog
parser (`rain.modules.tickets.syslog_parser` -- no third-party syslog
library, to keep the image's dependency surface small) behind a TCP server
and a UDP `DatagramProtocol` on the same port, both newline-delimited
(RFC 6587 non-transparent framing; octet-counted TCP framing isn't
supported). This is a **push** model: syslog-ng is configured with a
`network()` destination pointed at the worker, e.g.:

```
destination d_rain {
    network("<rain-host>" port(5514) transport("tcp"));
};
log { source(s_src); destination(d_rain); };
```

**Message format detection.** `syslog_parser` only strips the RFC
envelope (PRI, timestamp, host, tag) -- what's left, the message body
itself, isn't always plain text. `rain.modules.tickets.event_formats`
recognizes CEF (`CEF:...`, what most SIEMs/EDRs can emit, Wazuh
included), a JSON object, or loose Splunk-style `key=value` pairs, and
parses whichever it finds; a message that's none of those is left
exactly as `syslog_parser` produced it ("plain"). A recognized body's
extracted fields (CEF's header + Extension, the full JSON object, or
every key=value pair) are stored on `SyslogEvent.parsed_fields`, and
`SyslogEvent.message` becomes a human-readable one-line summary (CEF's
Name field, a JSON payload's `message`/`msg`/`rule.description`/
`full_log`, or a kv payload's `msg=`/`message=`/`description=`) instead
of the raw structured text -- so the live viewer, a promoted ticket's
title, and Event Promotion Policy matching against `message` all see
something legible regardless of source format.
Detection order is deliberately CEF, then JSON, then key=value last:
each is checked by its own marker (CEF's prefix, JSON's brace-wrapped-
and-actually-parses), while key=value is the loosest heuristic (needs
2+ pairs) and would false-positive on a CEF extension's own body if
checked first. `host`/`program`/`facility`/`severity` are untouched
either way -- they already came from the envelope, not the message body.

**Tenant routing.** The tenant isn't known yet at the point an event
arrives, so `control.syslog_source_map` (host/program pattern → tenant,
evaluated in order, first match wins) has to live in `control`, not a
tenant schema -- see `rain.modules.tickets.routing`. Unmatched events are
dropped; Admin > Syslog Sources shows the listener port and lets
`internal_admin` add mapping rules (a pattern of `.*` + regex acts as a
catch-all).

**Persistence + live viewer.** Every routed event is written to that
tenant's `syslog_events` (a rolling window, trimmed by a retention sweep --
`rain.core.tenant_config` holds the per-tenant `event_retention_days`,
default 14; promoted events are never deleted) and published to a
per-tenant Postgres `NOTIFY` channel (`rain.modules.tickets.live_bus`,
channel `rain_syslog_<schema>`). The live viewer
(`GET /tickets/live` + `WS /tickets/live/ws`) sends the last 50 buffered
events on connect, then forwards new ones as they're published; filtering
(by severity threshold and free-text) happens client-side in
`static/js/live.js` so the WebSocket protocol stays a plain one-way
server→client push. The WebSocket route resolves its session manually
(`rain.core.tenancy.resolve_ws_tenant_schema`) rather than through
FastAPI's `Depends()` chain -- that chain is typed against `Request`, and
FastAPI only special-cases an exact `Request`/`WebSocket` match even
though both are Starlette `HTTPConnection` subclasses with the same
`.cookies`.

The WebSocket payload itself only ever carries `message[:500]`, never
`raw`/`parsed_fields` (`live.py`'s `_event_payload`) -- too much to push
per event on a busy stream. `GET /tickets/live/{event_id}/full`
(`live.live_event_full`) is the fetch-and-inject fragment
(`tickets/_live_event_full.html`) that goes back to the DB for the
complete row, shown in `#live-message-modal` -- which lives in
`base.html`, not `live.html`, specifically so a ticket's own "Source
event" field (`[data-source-event]` in `app.js`, wherever `ticket.
source_event_id` is set) can open the identical window without a second
implementation: same route, same modal, same fragment, just a
different trigger reading a different id (a ticket's `source_event_id`
instead of a feed row's own `data-id`). 404s past the retention window
or a deleted event render inline in the modal rather than erroring the
page underneath it.

**Event Promotion Policies (rule engine).** Each persisted event is
checked against that tenant's active `ticket_rules`
(`rain.modules.tickets.rules.evaluate_and_promote`) in `sort_order`.
`TicketRule.promotion_type` picks one of three ways a policy decides
"this is worth a ticket" -- one table, one screen (`GET /tickets/rules/all`),
where a single/multi-event, regex/ML distinction used to mean two
separate models (TicketRule + CorrelationRule) evaluated by two separate
code paths; see `TicketRule`'s own docstring and migration 0038 for why
that split didn't earn its keep:

- `single`: a match (regex on `message`/`host`/`program`) becomes its own
  `Ticket` via `rain.modules.tickets.service.create_ticket`. A policy
  whose `ticket_type` is `change` also defaults that new ticket's
  `start_date`/`end_date` to "starts now, 24h turnaround"
  (`rules._default_change_window`) and, if `approval_flow_id` is set,
  attaches that flow (`service.start_approval`, the same machinery the
  manual "New ticket" form and Service Catalog use) -- only for a
  *newly created* change ticket, never one `repetition` folds an
  occurrence into.
- `repetition`: same match, but if the computed title equals an already-
  open ticket of this policy's type, the event folds into that ticket
  instead (`service.combine_event_into_ticket` -- a comment noting the
  repeat + `is_problematic` turned on) rather than creating a new one.
  `ml_sidecar_enabled` (on by default for a newly created repetition
  policy) additionally runs the event through the same anomaly-scoring
  path `ml_anomaly` uses below, against this same row's own
  `ml_algorithm`/`group_by`/`window_minutes`/`ml_score_threshold`/
  `ml_warmup_count` -- but a fire adds a comment to whichever ticket
  this call already touched (see `rules._annotate_if_anomalous`)
  instead of creating a second, separate one. Repetition and anomaly
  detection aren't competing concerns the way the three tabs on the
  policy form might suggest: repetition decides how an event's ticket
  gets produced, ML is an orthogonal statistical layer that can just as
  well watch the population repetition is already tracking (migration
  0043).
- `ml_anomaly`: scores every matching event (blank/`.*` pattern to mean
  "every event") against a per rule+group_key online model, trained on
  severity/message-length/hour-of-day -- deliberately small and numeric,
  not an NLP pass over the message -- and fires once the score clears a
  threshold, after a warm-up count of events. Which `river.anomaly`
  detector scores it is a per-policy choice (`TicketRule.ml_algorithm`,
  `rain.modules.tickets.rules.ML_ALGORITHMS`): Half-Space Trees (the
  default; a tree ensemble good at point anomalies), Local Outlier
  Factor (density-based, better at contextual anomalies, pricier per
  event), or One-Class SVM (a smooth boundary around "normal," best
  when normal behavior is stable) -- the only three of `river`'s six
  anomaly detectors that share the app's unsupervised `score_one(x)`/
  `learn_one(x)` call shape; the other three need a supervised target
  this app has no ground truth for. A model's pickled state persists on
  `TicketRuleState.ml_model`, read/written under `SELECT ... FOR UPDATE`
  since scoring-then-training is a read-modify-write, not a single atomic
  statement; the row is only ever written with bytes this module just
  pickled itself, never with anything from a request, so unpickling it
  back isn't a deserialization-of-untrusted-input concern. A running
  per-feature mean/variance (Welford's online algorithm,
  `TicketRuleState.ml_feature_stats`, plain JSON) rides alongside the
  model so a firing event's description can name the single most-
  deviated feature and how many standard deviations off this group's
  own history it was, instead of just a bare score. The scoring/
  statekeeping itself (`rules._score_for_anomaly`) is shared between
  this standalone type and the repetition sidecar above -- same model,
  same warm-up/threshold/cooldown gating either way; only what happens
  on a fire (a new ticket here, a comment there) differs, which is each
  caller's own job. `rules.rule_training_status`/`bulk_rule_training_
  summary` read `TicketRuleState.ml_event_count` back out against the
  rule's own `ml_warmup_count` for display -- a compact per-rule badge
  on the policy list ("Live", "115/250 training", or a mixed-group
  summary), and a full per-group breakdown on the rule's own edit page
  -- entirely a read of state `_score_for_anomaly` already maintains,
  no new bookkeeping.

Root cause assistance (`rain.modules.tickets.rootcause`) revisits a
ticket -- on demand (an "Analyze root cause" button on the ticket detail
page or its tickets-list row menu) or automatically, once, the first
time it's moved into an `is_closed` status, opt-in per tenant
(`auto_root_cause_on_close` tenant_config, off by default) -- computing
two honest, non-causal signals: a repeat-occurrence pattern (host/
program distribution and time span across every `SyslogEvent` promoted
into the ticket via `promoted_ticket_id`) and similar past *closed*
tickets (the same `websearch_to_tsquery`/`ts_rank` full-text search the
global search bar uses, scoped to `is_closed` statuses). Deliberately
not framed as "AI root cause analysis" -- nothing here, or in `river`,
does causal reasoning; both signals are things a human would otherwise
do by hand scrolling the timeline or searching past tickets, just
automated.

The on-demand path is a two-step, not a direct post: `POST /tickets/
{id}/analyze/preview` computes the analysis and returns it as a fragment
(`tickets/_root_cause_preview.html`) into a modal shared by both
triggers (base.html's `#analyze-root-cause-modal`, populated by app.js's
`[data-analyze-root-cause]` handler) -- nothing is persisted by this
step. From there, "Post as a comment" submits to the unchanged `POST
/tickets/{id}/analyze` (which recomputes the analysis itself rather than
trusting anything echoed back from the preview, so what gets posted is
always freshly computed), "Copy to clipboard" copies the shown text
client-side, and "Close" just dismisses the modal. The automatic-at-
closure path (`service.update_status`'s `newly_closed` hook) skips this
preview step entirely and posts directly, same as before.

`single`/`repetition` are evaluated first-match-wins (an event never
spawns two tickets that way); `ml_anomaly` policies never "consume" the
event the way those two do -- every active one still scores it against
its own model regardless of what a `single`/`repetition` policy above it
did, the same "alongside, not instead of" property a separate
CorrelationRule concept used to provide as two systems instead of one.
`Ticket`s numbers itself `INC-000123` / `VULN-000045` from a real
Postgres sequence (`inc_number_seq` / `vuln_number_seq`, one pair per
tenant schema, allocated through SQLAlchemy's `Sequence(...).next_value()`
so `schema_translate_map` resolves it to the right schema -- raw
`nextval('name')` SQL text would not, since translation only applies to
compiled schema-item constructs, not textual SQL). The same manual
"Promote to Incident/Vulnerability" buttons in the live viewer hit
`GET /tickets/new?source_event_id=...`, which pre-fills the form and
suggests an asset match by `external_id`.

**Notifications.** `rain.modules.tickets.notifications` sends email
(`aiosmtplib`) and Slack (`httpx` POST to an incoming webhook) on ticket
creation. The outbound SMTP relay is instance-wide
(`control.global_config`, set once in Admin > SMTP Relay, password
Fernet-encrypted); *who* gets notified is per-tenant
(`notification_channels`, config Fernet-encrypted the same way).

**Watchers.** `TicketWatcher` -- emailed on a ticket's new comments and
status changes, on top of whoever's actively working it. A row is
either `user_id` (a control.users id) or a bare `email` for someone
with no account, never both; email uniqueness per ticket is
case-insensitive, enforced by a partial functional unique index rather
than a plain column constraint. Three ways to end up watching:
toggling "Watch" on the ticket detail page yourself; being the
reporter (added automatically on creation, skipped for an anonymous
portal submission) or the assignee (added automatically on every
(re)assignment, `rain.modules.tickets.service.create_ticket`/
`update_assignee`); or a Platform Response Rule's "Add a watcher"
action, below.

**Platform Response Rules.** `rain.modules.tickets.platform_events`, a
second, independent rule layer on top of ticket creation -- reacts
*after* a ticket already exists (auto-promoted or manual), to one of
`TRIGGER_EVENTS`' seven triggers: an incident/vulnerability/change
being created (`evaluate_ticket_created`, hooked into `service.
create_ticket`, covering both origins), one of those three being
closed (`evaluate_ticket_closed`, hooked into `service.update_status`'s
`newly_closed` transition), or a change's approval flow clearing its
last step (`evaluate_change_approved`, hooked into `service.
decide_approval_step`'s `fully_approved` branch, alongside that
function's own `_emit_syslog_on_full_approval` sibling). Every active,
pattern-matching rule for the trigger that just fired runs, not just
the first (unlike the single-event rule engine above); all three
hooks funnel into the same `_evaluate_and_fire` core. Each hook is
imported locally at its call site (not at module level) to avoid a
cycle -- `platform_events` imports `service` at its own top level for
the actions below, so `service` importing `platform_events` back at
module level would be circular. Actions: notify Slack/email (reusing
`NotificationChannel`), call a webhook, attach a document or asset,
mark the ticket problematic, or add a watcher (email or system user,
see above). Every firing -- and each action's individual outcome, even
a failed one -- is logged to `platform_event_triggers` and the
ticket's own activity feed, so a failed Slack post doesn't hide the
fact the rule matched.

**Escalation.** A per-tenant "escalation webhook" (one `WebhookConfig`,
picked on Admin > Branding next to the portal's own settings, stored as
`tenant_config["escalation_webhook_id"]`) backs a manual escalate
button/menu item shown on every ticket detail page, the tickets list
and Kanban board's own row menus, and next to a signed-in portal
visitor's own tickets -- whenever a tenant has one configured, absent
otherwise. Its own label is a second tenant_config key,
`escalate_button_label` (default `"Escalate"`), rendered wherever the
button appears instead of a hardcoded string -- same idea as
`portal_shareable_documents_label`. Unlike a Platform Response Rule's
webhook action, this isn't pattern-matched or automatic: `rain.modules.
tickets.service.escalate_ticket` fires it for one ticket, on demand.

Two things get logged, not one: a terse field-change entry ("escalated
this ticket: `<webhook>` -> HTTP 200"), same as before, for a quick
scan of the activity timeline; and a real comment, attributed to
whoever clicked it, carrying the webhook's actual response body
(`_ESCALATION_BODY_MAX_CHARS`, 4000, caps it -- same "don't let a
receiving system's own error page dump an unbounded blob into the
ticket" reasoning as `documents.service`'s own diff cap). `escalate_
ticket` returns an `EscalationOutcome` (webhook name, success,
status_code, body, error) rather than the old bare outcome string, so
a caller can show more than "it worked" -- the ticket detail page, list
row menu, and Kanban card menu all do, via `app.js`'s `[data-escalate-
form]` handler and a shared `#escalate-modal` (base.html, alongside the
root-cause one). That handler intercepts the same `<form>` markup the
old redirect-based flow used (now `data-escalate-form` +
`data-confirm-text` instead of the generic `form[data-confirm]`
selector -- deliberately its own listener, not stacked onto that
generic one, since `preventDefault()` from one submit listener doesn't
stop a *later* listener on the same event from still running, so a
cancelled confirm() in the generic handler wouldn't have stopped this
one's fetch), then fetches `POST /tickets/{id}/escalate` with no
`next` field and renders the returned fragment (`tickets/_escalate_
result.html`) into the modal. `next`'s presence is what the route
branches on: sent (only the portal's own form still sends it, since it
has no modal to show a result in) means fire, then redirect there as
before; absent means fire, then return the fragment instead. Not
content negotiation (an `Accept` header) -- just the one field the
route already had a reason to read.

**Export.** `GET/POST /tickets/export/run` -- CSV/JSON/Excel with the
same configurable-column picker the Asset Registry exporter uses: a fixed
set of built-in columns plus, if the tenant has defined any, one
`field_<id>` column per tenant-wide ticket custom field (`custom_fields`
scoped `scope="ticket"` -- shares the table with assets' own custom
fields rather than a second one, see `CustomField`'s own docstring).
`POST /tickets/import/*` is the create-only counterpart -- CSV/JSON,
mapped columns become a new incident/vulnerability per row (a change
needs an approval flow attached by hand, so it's rejected here rather
than silently created without one).

**Document linking** (the ticketing spec's "link to a document repository
as a knowledge base") is live -- see Document Repository below.

**Kanban board.** `GET /tickets/kanban` (`router.kanban_board`) is a second
view over the exact same tickets `GET /tickets` shows -- same
`service.ticket_list_stmt`, same filter parameters (`ticket_type`,
`ticket_status`, `asset_id`, `assigned`, `problematic`, `prioritized`),
just grouped by
`Ticket.status` into columns instead of paginated into table rows. The
filter bar itself (type pills, status dropdown, asset picker, quick-filter
chips, and the `qs()` query-string builder both views' links use) was
pulled out of `tickets/list.html` into `tickets/_filter_bar.html` -- a
Jinja macro file imported `with context` by both templates -- specifically
so the two views' filters can't drift apart from each other; `qs()` takes
a `base` URL (`/tickets` vs `/tickets/kanban`) and an `include_sort` flag
(Kanban has no column-header sort, list.html does) as its only two
divergence points. No pagination: a board's point is seeing everything
that matches at once, not paging through it, so the query is capped
in-process at `_KANBAN_TICKET_CAP` (500) instead, with a banner telling
the tenant to narrow their filters (or use the table view, which still
paginates) if that cap was hit. Each card carries the identical row-menu
markup `tickets/list.html`'s own rows do (same actions, same conditions --
literally copy-pasted into a `kanban_card()` macro at the top of
`kanban.html`, since the two live in different templates and there's no
per-row Jinja include cheap enough to be worth it over a in-file macro
here); a ticket sitting on a status key no tenant-configured `TicketStatus`
row has any more (deleted out from under it) still gets a column, appended
after the configured ones and labeled "(removed status)", rather than
silently vanishing from the board.

Dragging a card is HTML5 drag-and-drop (`app.js`, no library) against a
small dedicated endpoint, `POST /tickets/{id}/kanban-status` -- everywhere
else a status change happens (the ticket detail page's status-stepper
buttons) is a traditional form POST + 303 redirect, which is the wrong
shape for a drag gesture that shouldn't reload the whole page on every
drop. This route calls the exact same `service.update_status()` the
stepper's own `/tickets/{id}/status` does, just returns `{"ok": bool,
"status"/"error": ...}` as JSON instead of redirecting. The drop handler
moves the card's actual DOM node into the new column immediately
(optimistic -- and a real node move, not a re-render, so the moved card's
own row-menu listeners are still attached afterward), then reverts it back
to its original column and shows a dismissing `.flash-error` if the
request comes back not-`ok` or fails outright. No approval-reset confirm
to replicate from the detail page's severity/title/assignee/asset edit
forms: a plain status change has never nullified a change ticket's
collected approvals on any of these routes, only editing those other
fields does, so a card move needs no `confirm()` before it fires. Columns
intentionally don't get their own vertical scroll container (the whole
page scrolls instead, same as every other view) -- `overflow-y` on a
column would clip a card's `.dropdown-menu-panel` (absolutely positioned,
CSS computes `overflow-x` right along with an explicit `overflow-y`) the
moment it tried to pop out past that column's own bottom edge.

**Group by: status vs. assignee.** A `group_by` query param (`"status"`,
the default, or `"assignee"`) picks what the board's columns actually
are, independent of every filter above -- a second, self-labeling
`<select>` (no separate `<label>`, same as the filter bar's own status
dropdown) living inside that same `<form>` in `tickets/_filter_bar.html`,
so either select's `onchange="this.form.submit()"` submits both
current values together. `qs()`, the filter bar's shared query-string
builder, reads an optional `selected_group_by` context variable the
same `default(none)`-guarded way it already reads `selected_sort`/
`selected_dir` -- present (and threaded onto every link/hidden-input it
builds) only for `kanban_board`'s own context; `list_tickets`'s table
view never defines it, so it never appears on a table-view link.
`"assignee"` columns come from `rain.core.user_names.list_assignable_users` (the
same tenant-scoped-users-plus-internal_admins candidate set the
assignee picker's own `search_assignable_users` predicate offers, just
the full list instead of a typed-in, capped-at-8 search) plus a
leading "Unassigned" column; a ticket assigned to someone no longer in
that set gets its own extra column, same "shown, not silently
dropped" treatment `extra_status_keys` already gives an orphaned
status, except deliberately not a drop target (no
`data-kanban-dropzone` on it) -- there's no sane "reassign to someone
this tenant can't assign to" action for a drop there to mean.

Dragging a card in assignee mode hits a second small endpoint, `POST
/tickets/{id}/kanban-assignee`, mirroring `kanban-status` exactly:
`service.update_assignee()`, JSON response, optimistic DOM move,
revert-and-flash on failure. It re-checks `is_assignable_user()`
server-side before accepting a drop the same way the ticket detail
page's own `/assign` route already has to -- the board only ever
*offers* this tenant's assignable users as columns, but nothing stops
a crafted POST naming an arbitrary id, and `data-assignee-id` is exactly
that kind of client-supplied value. `app.js`'s single Kanban drop
handler branches on `dropzone.dataset.assigneeId !== undefined` (a
presence check, not a truthiness one -- `data-assignee-id=""`, the
Unassigned column, is a real assignee-mode dropzone, not a missing
attribute) to decide which endpoint/body shape to send, and, on a
successful assignee-mode drop, updates the moved card's own visible
assignee name (`kanban_card()`'s meta line, given its own `<span
data-kanban-assignee>` for exactly this) -- the one piece of card
content a move actually changes in this mode, unlike status mode where
nothing on the card's own face reflects its column.

**Narrowing assignee columns to one team.** Every assignable user can
be a lot of columns on a tenant with many accounts, so a second query
param, `assignee_group` (a `Group.id`), narrows the column set to one
tenant Group's own members -- a third filter-bar `<select>`, rendered
only once `group_by == "assignee"`, listing every `Group` in this
tenant (plain `select(Group).order_by(Group.name)`, no scoping query
needed beyond that: `Group` already lives in the tenant schema, so
`tenant_db` can only ever see this tenant's own rows) plus "All
members". `kanban_board` intersects `list_assignable_users`' result
with that group's `GroupMembership.user_id` set when `assignee_group`
is set, then runs the exact same column-building logic as before --
still one column per *person*, not per group, so dragging a card is
unchanged: it assigns to that specific individual, exactly as it did
before this existed. A ticket assigned to someone outside the selected
group gets the same extra-column-not-a-drop-target treatment as
someone no longer assignable to the tenant at all (both are, from
`known_user_ids`' perspective, simply not in the current column set).
Deliberately not a "columns are teams" redesign -- a ticket has exactly
one `assignee_user_id`, no group-assignment concept exists in the
schema, and asking what a drop onto a team's own column should even
mean surfaced enough real ambiguity (assign to least-loaded member?
prompt for one? no drop at all?) that it was worth confirming rather
than guessing: individual columns, just fewer of them at a time.

### A routing bug worth knowing about

While wiring `/tickets/live` in next to `/tickets/{ticket_id}`, a
pre-existing routing bug surfaced: FastAPI/Starlette match routes
by trying each registered pattern in order, and a bare `{param}` segment
(default `str` converter) matches *any* single path segment -- including
ones meant for a different, later-registered literal route. `POST
/assets/types`, `/assets/fields`, `/assets/export`, and `/assets/sync` were
all silently unreachable, shadowed by `POST /assets/{asset_id}` registered
earlier in the same file: FastAPI would try to parse `"types"` as
`asset_id: int`, fail, and return 422 rather than ever falling through to
the intended handler. Fixed throughout both routers by giving every
numeric path parameter an explicit converter (`{asset_id:int}`,
`{ticket_id:int}`, ...), which makes the *route pattern itself* only match
digits, so Starlette correctly skips it for non-numeric segments regardless
of registration order. `backend/.stub_check` (not committed) had a small
script that instantiates the app and asserts no literal path incorrectly
matches a dynamic sibling pattern -- worth re-running by hand after adding
new routes.

### Two filter-bar gotchas worth knowing about

**An `int | None` query param and a `<select>`'s "clear" option don't
mix.** FastAPI/Pydantic reject an `int | None` query param outright (a
raw 422) the moment it arrives as an empty string, rather than treating
that the same as the param being absent -- but an empty string is
exactly what a plain `<select>` with a `value=""` "clear this filter"
option (`assignee_group`, `owner_group`, `filter_owner`) or
`_search_picker.html`'s own always-present hidden input (`asset_id`)
actually submits on a normal GET form submission, not just omitted
from the URL. Confirmed live: clearing any of those filters 422'd
instead of falling back to "no filter". `rain.core.query_params.
optional_int` is the fix -- type the affected param `str | None`
instead, then `x = optional_int(x)` (reusing the same name) at the top
of the route body, same as `group_by`'s own "clamp to a known value"
reassignment right next to it.

**A `<form>` holding more than one `<select>` stacks them unless told
not to.** `app.css`'s global `select { width: 100%; }` (so a lone
select in its own `.field` fills it, the common case) means each
select in a *shared* form -- `tickets/_filter_bar.html`'s Status/Group
by/team selects, `documents/kanban.html`'s Group by/team/tag/owner
ones -- individually claims the entire row for itself, which reads as
the selects stacking vertically one per line rather than sitting side
by side, even though the form itself is a flex child of `.filter-bar`
elsewhere (being a flex *item* doesn't make an element's own children
flex, only `display: flex` on the element itself does). Confirmed
live: exactly this, before `.filter-bar-controls`
(`display: flex; flex-wrap: wrap; gap: 8px;`, replacing the plain
`.field` these forms used to carry) and `.filter-bar-select`
(`width: auto;`, added to every select inside one) existed.

## Document Repository

**Storage.** `rain.modules.documents.storage` is a small `StorageBackend`
protocol (`save`/`read`/`delete` on an opaque string key) with two
implementations: `LocalStorageBackend`, writing under
`{uploads_dir}/documents/<tenant_schema>/<random-token>-<filename>` on the
shared `rain_uploads` volume, and `S3StorageBackend`, writing the same key
(prefixed `documents/`) as an object in whichever bucket `Settings.s3_bucket`
names -- `get_storage()` picks one based on that setting; nothing in the
router or service layer touches the filesystem or an S3 client directly.
`S3StorageBackend` uses plain (synchronous) `boto3`, not an async wrapper,
matching `StorageBackend`'s existing signature -- every caller already
invokes these as blocking calls from inside an async route handler (the
same trade-off local disk I/O already made), so this doesn't introduce a
new async/sync split, just a second implementation of the same
already-synchronous contract. `s3_endpoint_url` is what makes it work
against any S3-compatible service (MinIO, etc.), not only real AWS S3 --
verified live against a MinIO instance: save/read/delete all round-trip
correctly, and a bucket listing after a save/delete shows the object
appearing and disappearing exactly when expected. `make_storage_key()`
both namespaces by tenant and strips any path components from the
uploaded filename (`Path(name).name`), so a filename like
`../../etc/passwd` can't escape the tenant's subtree (or, for S3, land
outside the `documents/` prefix) either way.

Branding assets (`rain.web.uploads` -- the logo, and the client portal's
optional background image) are always *served* straight off the
local static mount (`/media/branding`) regardless of `s3_bucket` -- an S3
object can't be, without a signed-URL redirect this app doesn't have --
but every upload also writes a durable backup (S3 under its own
"branding" prefix in the same bucket when `s3_bucket` is set, its own
row in `control.branding_assets` otherwise), restored to local disk at
startup if it's missing there. The CSV/JSON import stash stays on local disk
unconditionally, with no backup at all -- it's transient by design, gone
once the import finishes, nothing worth persisting. Both are small
enough either way that this doesn't undercut S3's actual purpose here:
document bodies, which can be large and numerous, are what "eliminate the
uploads volume" is actually about.

**Access control.** Documents are *never* served through the static file
mount. `/media` was previously mounted over the whole `uploads_dir` --
harmless while it only held branding logos, but the document repository
also uses that volume for tenant documents and the CSV/JSON import stash,
both of which must stay tenant-scoped and authenticated. Fixed by mounting only
`/media/branding` (the one thing that legitimately needs to be
fetchable pre-auth, for the login/setup page); documents are downloaded
exclusively through `GET /documents/{id}/download`, which goes through the
normal `get_tenant_db` dependency chain (login + correct tenant schema
required) and always responds `Content-Disposition: attachment` so a
browser never renders an untrusted upload inline in the app's origin
regardless of its claimed `mime_type`.

**Records.** `documents` (`DOC-000123` numbers from a per-tenant
`doc_number_seq`, same `Sequence(...).next_value()` pattern as ticket
numbering) plus `document_links` -- a polymorphic join table
(`linked_type` `asset`|`ticket`, `linked_id` a plain integer, since Postgres
can't FK into two different target tables). `rain.modules.documents.service`
is the only place that touches either table; `links_for(db, linked_type,
linked_id)` is what the asset edit page and ticket detail page call to
render their "Linked Documents" panel
(`documents/_links_fragment.html`, shared by both).

**Flow.** Upload from the general repository (`/documents/new`) or directly
from an asset/ticket page's "+ Attach document" link, which pre-fills and
auto-links via hidden `linked_type`/`linked_id` fields on the same upload
form -- one POST creates the `Document` and the `DocumentLink` together.
Documents can also be linked to additional assets/tickets later from the
document's own detail page.

**Change alerting.** `Document.alert_on_change`, when set, raises a
synthetic `SyslogEvent` (host `documents`, program the doc number) whenever
the stored content actually changes -- from a webhook refresh
(`service.refresh_from_webhook`) or a manual inline edit
(`service.update_body`), both funneled through the same `_content_changed`/
`_diff_summary` pair so the two paths can't drift on what counts as a
change. `_content_changed` compares `str.splitlines()` on both sides, not
raw string equality: confirmed live that a plain `!=` flagged a save as
"changed" purely from a trailing-newline artifact between the stored file
and a freshly-submitted textarea body, which is exactly the class of
insignificant, not-a-real-edit difference this needs to ignore. The event
itself then runs through the normal Event Promotion Policy pipeline
(`rules.evaluate_and_promote`) like any real inbound syslog line -- a
self-generated event feeding the same pipeline rather than a
second, parallel notion of "event." `_diff_summary` (a capped
`difflib.unified_diff`) goes in the event's `raw` field so the
before/after is visible at a glance rather than just "something changed."
`rain.modules.tickets.service._emit_syslog_on_full_approval` (Change
approvals, below) reuses this exact same synthetic-event convention.

**Refresh when rendering.** `Document.refresh_on_view` (tenant migration
0046) is a third and fourth caller of the refresh logic, alongside the
manual "Refresh from webhook" button and the calendar sweep's
`refresh_document` policy above -- both places a document's content is
actually rendered for someone to read call it before reading the stored
body, when the flag is set and `webhook_id` is configured:
`rain.modules.documents.router.document_detail` (the document's own page,
via `service.refresh_from_webhook`, one document) and `rain.modules.
home.router.home` (Home, via `service.refresh_many_from_webhook`, since
more than one document can be flagged `show_on_landing_page` +
`refresh_on_view` on the same load -- see "Concurrent webhook refresh"
below). Neither ever writes on a failed call (only a successful one
reaches the diff/save step), so this falls out for free from the
existing function rather than needing its own success/failure branching:
a successful call has already overwritten storage by the time either
route reads the body, and a failed one leaves it untouched. The two
callers differ only in how (not whether) a failure surfaces:
`document_detail` passes `outcome.error` through as `webhook_refresh_
error` for the template to flash a small notice ("showing the last saved
version instead"); `home` ignores the outcome entirely and just falls
back silently -- one document's stale webhook response isn't worth a
banner on a page that may be showing several.

**Concurrent webhook refresh.** `service._apply_webhook_result` is the
diff/save/commit/alert half of a refresh, factored out of `refresh_from_
webhook` so `refresh_many_from_webhook` can reuse it per-document after
gathering several `WebhookResult`s at once. The split matters because an
`AsyncSession` isn't safe for concurrent use from multiple coroutines --
the database half of a refresh has to stay sequential on whichever
session the caller holds, but `webhook_service.call_webhook` itself
touches nothing but network I/O and an already-fetched `WebhookConfig`
(no shared session), so it doesn't have that constraint.
`refresh_many_from_webhook` batches its `WebhookConfig` lookups into one
query (`webhook_service.get_webhooks`, a `WHERE id IN (...)`, rather than
one `get_webhook` round-trip per document), fires every eligible
document's `call_webhook` concurrently via `asyncio.gather`, then applies
each result through `_apply_webhook_result` in a plain sequential loop.
On a Home load with several slow webhooks flagged, this turns what used
to be N sequential waits (each up to that webhook's own
`timeout_seconds`) into roughly one wait, all in flight together --
`document_detail`'s single-document path is unaffected, still one
`refresh_from_webhook` call, still synchronous in the request either
way (a slow or hung webhook still delays that page load by up to
`timeout_seconds`, same trade-off the manual button already makes, just
now on every render instead of one click).

**Freshness display.** Both render sites above compute the same
`last_updated = last_refreshed_at or updated_at or created_at` -- the
first if this document's ever had a successful webhook call (refresh-
when-rendering included), else the second, else the third. Not a precise
"content last actually changed" signal -- `updated_at` moves on any saved
field on the row, not just the body, and `last_refreshed_at` moves on a
refresh whose response was identical to what's stored -- but the best one
available without a dedicated column, and consistent with what "Last
refreshed" already showed next to the manual button on the Auto-update
tab. The document's own Contents tab shows it as a small "Last updated
`<timestamp>`" line above the editor; Home shows it as a pill ("Version
from `<timestamp>`", `.doc-version-pill`) next to that document's title,
in a shared `.card-title-row` alongside `.card-title` (baseline-aligned,
so the pill's text sits level with the title's own rather than centered
against its full line-height).

**Tags.** `Document.tags` (`text[]`, tenant migration 0039) -- optional,
freeform, comma-separated on input (`rain.modules.documents.service.
parse_tags`: trimmed, deduped case-insensitively keeping first spelling,
capped at 20). A plain array column rather than a normalized tags/
document_tags join table: nothing here needs a tenant-wide tag registry
or tag-scoped browsing, just tagging a document and finding it by that
tag later, and the array feeds directly into `search_vector` (Search,
below), which a join table's `GENERATED` expression couldn't reference
at all. See that section for the `IMMUTABLE`-function workaround folding
an array into a `tsvector` needed.

**Calendar link.** `CalendarEntry.document_id` (tenant migration 0040,
`ON DELETE CASCADE`) is a plain "this entry is about this document"
association -- independent of `CalendarEntry.policy_ref`'s existing
`refresh_document` auto-update mechanism (an opaque JSON policy blob
acted on by `rain.modules.calendar.sweep` on each due occurrence --
`service.refresh_from_webhook` for the referenced document, same call
its own "Refresh from webhook" button makes). Backs a document's own
Calendar tab (`rain.modules.calendar.service.list_entries_for_document`)
and the calendar entry form's "Related document" picker; picking a
document there and also checking "auto-refresh" sets both `document_id`
and `policy_ref` from the one selection, so the two never point at
different documents by construction. 0040 backfills `document_id` from
any pre-existing `policy_ref.document_id` (the only shape `policy_ref`
has ever had) so an entry that already auto-refreshed a document shows
up on that document's Calendar tab immediately, not just newly-created
ones.

**List-view flags and tag filtering.** `documents/list.html` shows a
small icon next to a document's number for each flag it has set --
`show_on_landing_page` (Home icon), `webhook_id` (a refresh icon,
tooltip distinguishing `refresh_on_view` from a manual-only refresh),
a calendar link (calendar icon, from a new
`calendar.service.document_ids_with_calendar_entries`, one distinct
query for the whole page rather than `list_entries_for_document`
called once per row), and `is_shareable` (a shield icon, tooltip
naming whatever `portal_shareable_documents_label` is currently set
to). Deliberately one color for all four rather than one per flag --
a row with several set stays legible instead of turning into competing
colored dots; each icon's own `title` carries the actual meaning. A
tag `<select>` next to the search box (`service.list_all_tags`, a
`SELECT DISTINCT unnest(tags)`) and each tag badge in the Tags column
both link to `?tag=<tag>`, an exact-membership filter
(`Document.tags.any(tag)`, not another substring `ILIKE` the way the
search box's own tag matching works) added to `document_list_stmt`
alongside its existing `search` filter -- either one narrows the list,
together or apart.

**Documents Kanban board.** `GET /documents/kanban` (`router.
documents_kanban`) is a second view over the same `document_list_stmt`
the list screen uses, the same "same query, different layout" shape
`tickets/kanban.html` established for tickets -- grouped into columns
instead of paginated table rows, `group_by` picking what the columns
*are*:

- `"tag"` (default): columns are `service.normalize_tag`'s
  (`.strip().capitalize()`, applied uniformly) canonical form of every
  tag in use, deduplicated *across* documents -- "security"/"SECURITY"/
  "Security" on three different documents all collapse onto one
  "Security" column, deterministically, with no "whichever document
  happened to be read first" ambiguity, since the same pure function
  produces the same output regardless of input order. Plus a leading
  "Uncategorized" column for documents with no tags at all. A document
  with several tags appears as its own card in *each* one
  (`data-tag-value` on the card records which specific tag that
  instance represents) -- confirmed live: a document tagged both
  "security" and "OnCall" showed up in both the "Security" and
  "Oncall" columns, once each.

  Dragging a card between tag columns retags it -- `POST /documents/
  {id}/kanban-tag` -> `service.retag(from_tag, to_tag)` -- a *targeted
  swap* (remove the one tag this card instance represented, add the
  one it was dropped on), not a wholesale replace: every other tag
  already on the document is left untouched. This was an explicit
  design fork worth confirming rather than guessing at: a document can
  carry several tags at once, unlike a ticket's single status/
  assignee, so "what does dragging one of its cards even mean" had
  three genuinely different reasonable answers (retag/swap, add
  without removing, or a read-only browse-only board) before the
  answer above was picked. Dropping onto a tag the document already
  carries (matched via `normalize_tag`, so case differences still
  merge) removes the origin tag without adding a duplicate --
  confirmed live -- and `app.js`'s drop handler then removes the now-
  redundant card from that column instead of showing two for the same
  document. Dropping into "Uncategorized" (an empty `to_tag`) just
  removes, with nothing added.

- `"owner"`: a workload view, the same shape as the tickets board's own
  assignee mode -- one column per this tenant's assignable users
  (`rain.core.user_names.list_assignable_users`) plus a leading "No
  owner" column, optionally narrowed to one Group's own members via
  `owner_group`. `Document.owner_user_id` (migration 0047) is a new
  column, separate from `uploaded_by` (a one-time fact about who
  created the document, never reassigned) -- who's *currently*
  accountable for keeping a document accurate, reassignable at any
  time the same way `Ticket.assignee_user_id` already is. Dragging a
  card between owner columns reassigns it -- `POST /documents/{id}/
  kanban-owner` -> `service.update_owner()` -- a single-valued move,
  unlike tag mode: a document has exactly one owner. Same
  `is_assignable_user()` server-side re-check before accepting a drop
  as the tickets board's own `kanban_update_assignee` -- confirmed
  live, a crafted id outside this tenant's assignable set is rejected
  with `{"ok": false, ...}` rather than written.

Each mode also accepts a plain filter on the *other* axis --
`filter_owner` (a person) narrows `"tag"` mode's underlying document
set before building tag columns, `filter_tag` narrows `"owner"` mode's
the same way before building owner columns -- both just pass through
to `document_list_stmt`'s existing `tag`/`owner_user_id` parameters.
Neither is a second grouping dimension (filtering "group by tag" down
to one single tag, or "group by owner" down to one single owner, would
just hide every other column for no reason), so each control only ever
renders in the mode it doesn't already group by.

`app.js`'s Kanban drag-and-drop is one shared `setupKanbanBoard()`
function, extracted this same round from what was previously
tickets-only inline code -- both boards' cards/dropzones/optimistic-
move/revert-on-failure mechanics are identical, only `buildRequest()`
(which endpoint, which body, what a success response means for the
dragged card) differs per board and mode.

A search/filter combination matching zero documents is not an error --
`documents_kanban` still renders the board (every column already says
"No documents." on its own, the same empty-state every column has
regardless of cause), just with `no_matches=True` added to the
context, which the template turns into one plain-text line above the
board so an all-empty board reads as "nothing matched", not as
"something's broken".

## Home

`rain.modules.home`, the smallest module in the app -- one route
(`GET /home`), one template, no service.py. What `GET /` (`rain.main`'s
own `index` route) redirects a signed-in user to instead of straight
into Records Authority, and the default `next` every login flow falls
back to (`Form("/")`, which itself now redirects to `/home`) -- a
neutral first screen rather than assuming tickets are what everyone
wants first. Registered in the sidebar as its own top-level `NavNode`
(`order=5`, ahead of Records Authority's `10`) with no children, the
first case in this app of a depth-0 nav node that's a plain link
(`.nav-link`) rather than a toggle (`.nav-toggle`) -- both were already
handled identically by `render_nav`, this just exercises the
previously-unused branch for real.

Content comes from `Document.show_on_landing_page` (migration 0045,
same opt-in-per-document shape `is_shareable` already established for
"Shareable documents," and independent of it -- a document can be
either, both, or neither): every document with the flag set (from its
own Properties tab) renders on Home, ordered by title, in place of the
route's own plain "Welcome to `<instance>`" fallback text (which never
renders at all once at least one document is flagged). Rendering reuses
`rain.modules.documents.textbody` exactly the way `document_pdf`
already does -- `body_kind()` picks Markdown vs. plain text vs. "no
inline body at all" (silently skipped, not an error, since a flagged
PDF/image has nothing to render), `render_markdown()` for Markdown
(already `bleach`-sanitized, safe to inject via `|safe`), plain text
left for Jinja's own autoescaping to handle safely on its own. No new
rendering path, no new sanitization surface -- this is the third
consumer of `textbody`'s existing functions (inline editor preview and
PDF export being the other two), not a new one.

## Search

Keyword search only -- no vector/semantic search, because there's no
LLM or embedding API wired into this app to turn a query into a vector
in the first place. Considered and rejected: a locally-computed
hash-based pseudo-embedding (a "hashing trick" bag-of-words vectorizer,
no model or network call needed); it wouldn't actually be semantic (no
synonym/meaning understanding) and its quality is often close to or
worse than plain full-text search, so shipping it as "vector search"
would read as a misleading claim.

**Index.** `tickets.search_vector`/`documents.search_vector` are
`GENERATED ALWAYS AS ... STORED` `tsvector` columns (tenant migration
0023) built from `ticket_number`/`title`/`description` and
`doc_number`/`title`/`tags`/`description` respectively, weighted
(`setweight`, number/title `'A'`, tags/description `'B'`), GIN-indexed.
Metadata only, not a document's file body -- indexing arbitrary
uploaded file content is a bigger feature this doesn't attempt.

`documents.tags` (`text[]`, tenant migration 0039) folding into a
`GENERATED` column needs a plain `text` blob for `to_tsvector()` first,
and Postgres requires that generated expression to be `IMMUTABLE` --
neither `array_to_string(tags, ' ')` nor a `tags::text` cast qualifies
(both `STABLE`, confirmed live: `ALTER TABLE ... ADD COLUMN ...
GENERATED` against either raises "generation expression is not
immutable"), and `array_to_tsvector(tags)` -- `IMMUTABLE`, but its
lexemes don't participate in `@@` matching via `websearch_to_tsquery` at
all (confirmed live: even an exact, no-stemming-needed tag came back
false). 0039 instead defines a tiny `IMMUTABLE`-marked SQL wrapper
function per tenant schema (`"{schema}".immutable_array_to_string`,
dropped along with the schema itself -- no shared/`public`-schema
leftover) purely to satisfy Postgres's immutability check for a case
that doesn't actually risk anything (a tenant schema's own collation
isn't changing under a `STORED` column).

**Query.** `rain.modules.search.service.search()` runs two independently
ranked queries (`ts_rank` + `websearch_to_tsquery`, which parses quoted
phrases/OR/-exclusions the way a search box's users expect) and merges
the results in Python -- small enough result sets in practice that a
single cross-table UNION query isn't worth the complexity. Match
highlighting uses `ts_headline` with sentinel `StartSel`/`StopSel`
markers, escapes the *entire* returned string first, and only then
replaces the sentinels with real `<mark>` tags -- so a highlighted
snippet can never smuggle in unescaped HTML from a ticket/document's own
(user-authored, never sanitized) title or description.

**Number shortcut.** Typing a ticket/document/asset number (`INC-000001`,
`DOC-000004`, `CI-000001`, tolerant of a missing zero-pad) redirects
straight to that record via `find_by_number()` instead of showing a
results page that could only ever contain it. Assets aren't otherwise
part of `search()` -- no `search_vector` column -- but a typed-in CI
number is still an exact, unambiguous lookup the same way a ticket/
document number is.

**Unpopulated pgvector columns.** `control` enables the `vector`
extension once, database-wide (`CREATE EXTENSION IF NOT EXISTS vector`,
control migration 0006 -- extensions are per-database, not per-schema,
so this doesn't repeat per tenant); `tickets.embedding`/`documents.
embedding` (`pgvector.sqlalchemy.Vector(1536)`, tenant migration 0023)
are nullable and completely unpopulated -- nothing in this app writes or
reads them. There's no plan to wire up an embedding source; the columns
are a leftover from an earlier design pass, kept only because dropping
them is its own migration for no functional gain over just leaving two
always-null columns in place.

**`Settings.enable_pgvector`** (`ENABLE_PGVECTOR` in `.env`, on by
default) makes all of the above skippable: some managed Postgres
instances either refuse `CREATE EXTENSION` to the app's own role
(confirmed live: `asyncpg.exceptions.InsufficientPrivilegeError` against
a standard, non-superuser RDS role) or don't offer `vector` at all
(standard RDS in AWS GovCloud) -- since nothing reads or writes these
unpopulated columns, failing the whole migration chain over an
extension nothing depends on isn't worth it. Off, control migration 0006's
`CREATE EXTENSION` and tenant migration 0023's two `add_column` calls
are no-ops (0023's `search_vector`/GIN part is unaffected -- it needs
nothing beyond stock Postgres); `rain.db.tenant_models` reads the exact
same setting at import time to decide whether `Ticket`/`Document` map an
`embedding` attribute at all, not just whether the column exists in the
DB -- a bare `select(Ticket)` selects every *mapped* column by default,
so a mismatch between "the DB doesn't have this column" and "the ORM
still thinks it does" would fail every ticket/document query, not just
ones that actually touch `embedding`. Confirmed live end-to-end against
a Postgres with no `vector` extension available at all: migrations
complete, and a plain insert + `select(Ticket)` both succeed.

### Ticket/document URLs

`/tickets/{ticket_number}` and `/documents/{doc_number}` (e.g.
`/tickets/INC-000001`) instead of the internal integer id. Each router
registers a custom Starlette path converter (`_TicketRefConvertor`/
`_DocRefConvertor`, regex-constrained to `(?:INC|VULN|CHG)-\d+|\d+` /
`DOC-\d+|\d+`) rather than using a plain `{ref}` string parameter --
a bare string converter matches *any* single path segment and would
shadow every literal route registered after it in the same router
("/new", "/rules", "/export/run", ...) regardless of file order, the
exact failure mode described below in "A routing bug worth knowing
about". The regex constraint means this route structurally can't match
a literal route's path at all, so there's no registration-order
dependency to get right. Falls back to the bare integer id for any
link/bookmark built before this switch (`get_ticket_by_ref`/
`get_document_by_ref` try the number first, then the id if the ref is
all-digits) -- a couple of harder polymorphic spots (a document's
"linked ticket" display, which only stores a bare `linked_id`, not a
loaded `Ticket`) were deliberately left on that fallback rather than
force a bigger data-model change for one display link.

## Client Portal

`rain.modules.portal`, a single page at `/portal/<tenant slug>` with no
sidebar/topbar -- reachable with or without a session
(`get_current_user_optional`, not `get_current_user`), unlike every
other tenant-scoped route in the app. Tenant resolution here is purely
from the URL slug, not the session (`_resolve_portal_tenant`), which is
the whole reason this is its own module instead of a route on
`rain.modules.tickets.router`: it can't use `get_request_context`/
`get_tenant_db`, both of which assume a session already picked a
tenant. `_resolve_portal_access` is the choke point every route except
the page itself shares for tenant resolution and the wrong-tenant/
require-auth gate, so those routes (submitting a ticket, opening a
catalog form, the ticket timeline) can't silently drift on what's
allowed through. `portal_form` (the page itself) uses the narrower
`_resolve_portal_tenant_and_flags` instead and applies its own looser
gate -- see "Shareable documents" below for why.

**Gating.** Two `TenantConfig` flags an admin sets on Admin > Branding:
`portal_require_auth` (off: anyone with the link can file anonymously,
the ticket records "an unauthenticated user" as the reporter) and
`portal_branded` (off: a plain, unaccented page showing only the
tenant's own name, for a portal shared outside the organization). A
signed-in visitor whose own tenant isn't the one in the URL is always
turned away with a plain 403, regardless of `portal_require_auth` --
that flag controls whether *an* account is required, not whether an
account for a *different* tenant is accepted.

**One tabbed layout, for every visitor.** Every visitor -- signed in or
not -- gets the same `.portal-shell.portal-wide` layout: a tab bar
(labels are visitor-facing copy, not the underlying concept -- "Request
Something" is the catalog tab, "Report Something" the incident-report
tab) plus "Today's events" above it, tenant-wide operational information
shown regardless of sign-in status. `rain.modules.calendar.service.
list_due_today` is what actually backs it -- `list_entries_due_today`
(CalendarEntry occurrences, reusing the month-grid view's own occurrence
math) *plus* `list_changes_in_range(db, today, today)` (change tickets
whose window covers today), the same two sources `rain.modules.calendar.
router`'s own grid-building combines into `by_date`/`changes_by_date`.
`list_entries_due_today` alone used to back this directly, which
under-counted relative to the full calendar page for any day that also
had a change scheduled on it. Both `Ticket` and `CalendarEntry` expose
`.title`, so the merged list needs no per-type branching to render --
`portal/report.html` additionally checks `e.ticket_number is defined`
(Jinja's attribute-lookup-turned-`Undefined` mechanics, safe against the
plain `AttributeError` a `CalendarEntry` raises for that name) to prefix
a change's ticket number, matching how the month grid's own chip labels
one (`calendar/month.html`'s `calendar-entry-chip-change`). Request
Something and Report Something are both open with or without a session
-- gated only by `portal_require_auth` below, same as ticket filing
always was, since `rain.modules.catalog.service.submit_catalog_item`'s
`reported_anonymously` flows straight through to
`ticket_service.create_ticket` exactly like the plain incident form's
already did. A signed-in visitor additionally gets a search bar and two
more tabs -- Pending Actions (backed by `rain.modules.tickets.service.
list_tickets_pending_approval_for`, the same eligibility rule
`is_eligible_approver` uses, evaluated as a set query, and excluding a
ticket sitting on an `is_closed` status -- a change closed or cancelled
out from under a still-`"pending"` `ChangeApproval.overall_status`
otherwise stayed listed here forever, since closing a ticket this way
never touches the approval row itself) and Document Archive -- both of
which stay session-gated (`{% if user %}` around their tab button and
panel alike, not just their content), since neither an approval decision
nor the document repository was ever meant to be reachable anonymously. `.content-standalone` (base.html's `<main>` for
login/setup/portal alike) is a centered flexbox; overridden to normal
top-down block flow specifically when a `.portal-shell` is present
(`.content-standalone:has(.portal-shell)`, same `:has()` technique as
the sidebar-collapse override) so switching between tabs of different
heights doesn't recenter -- and visibly jump -- the whole page.

**Escalate.** Next to a signed-in visitor's own tickets in the Report
Something tab, whenever the tenant has an escalation webhook configured
-- same feature as the ticket detail page's own Escalate button, see
Ticketing's Escalation section above. Posts to the same
`/tickets/{id}/escalate` route `require_login` already gates, with a
`next` field so it returns to the portal instead of a ticket detail
page this visitor might not even be allowed to open on its own
(`portal_require_auth` off doesn't imply this visitor can view
`/tickets/<n>` -- that's still `require_login`).

**Ticket timeline modal.** Clicking a ticket number in Report
Something's own table opens `GET /portal/<slug>/tickets/<ref>`
(`portal_ticket_timeline`) into a modal instead of navigating to the
full ticket page -- signed-in-only, and only for a ticket this visitor
reported themselves (`ticket.reporter_user_id == user.id`), tighter
than what a `client`/`client_admin` could reach via the full app (any
ticket in their tenant), matching this page's own narrower ethos. A
404 either way for "not signed in," "no such ticket," or "not yours" --
never 403, so a wrong-visitor request doesn't learn which one it was.
Renders the exact same entries `rain.modules.tickets.service.
build_activity` produces for the full ticket detail screen and the PDF
export (moved there from `tickets.router` specifically so the portal
could reuse it, along with the `assignment_change_ids`/
`asset_change_ids`/`asset_names` helpers it depends on) -- content and
wording are shared via `tickets/_activity_entry.html`'s `entry_content`
macro, which both this fragment and `tickets/detail.html` call; only
the wrapper differs (a ServiceNow-style dotted vertical timeline here,
a flat list there). Client-side "Newest first"/"Oldest first" re-sorts

**Shareable documents.** A `Document.is_shareable` flag (set from the
document's own page) exposes it through a portal tab reachable by
*every* visitor, including one with no session at all, even on a
tenant with `portal_require_auth` on -- "Trust Center"-style content is
meant to stay public regardless of whether the rest of the portal
requires an account. `portal_form` fetches this tenant's shareable
documents before applying its own auth gate: with none, an anonymous
visitor on a `portal_require_auth` tenant is still redirected to
`/login` exactly as before; with at least one, they're let through in
an `anonymous_shared_only` mode that renders nothing but this tab (Today's
events, Request/Report Something, and the two signed-in-only tabs are
all suppressed in that mode -- letting shareable documents through
isn't meant to loosen anything else `portal_require_auth` was gating).
The tab's label is a tenant_config value
(`portal_shareable_documents_label`, default "Shareable documents",
renamable on Admin > Branding) rather than a fixed string, and the tab
itself only renders once the tenant has at least one shareable
document. Downloads go through a dedicated, always-public
`GET /portal/<slug>/shared-documents/<doc_ref>/download` -- not
`rain.modules.documents.router.download_document`, which is
`require_login` and resolves its tenant from the session, neither of
which fits a visitor with no account -- 404 for a document that
doesn't exist in this tenant or exists but isn't `is_shareable`.
already-rendered `[data-at]` entries in place, no re-fetch -- the exact
same mechanism the ticket detail page's own toggle uses
(`activateActivitySortToggle` in app.js), refactored into a named,
re-callable function and exposed as `window.RAIN.
activateActivitySortToggle` specifically so this modal's fetched-after-
page-load fragment can activate its own copy, which the original
page-load-time-only binding could never have found. Modal shell/open-
close plumbing is portal-page-local (`report.html`), not base.html's
shared `#doc-preview-modal`, since that one is wrapped in `{% if ctx %}`
and never renders on this `content_alone` page at all.

## Service Catalog

`rain.modules.catalog`. `ServiceCatalogItem` (name, description, ticket_
type, default_severity, payload_format, requires_approval/approval_flow_
id, is_active) plus up to 10 `ServiceCatalogField` rows per item (field_
key, label, field_type -- the same set `rain.modules.assets.schemas.
FieldType` already defines, reused rather than duplicated -- select_
options, is_required, sort_order). Configured under Admin > Tenant
Administration > Service Catalog (`admin.router`'s `/admin/catalog*`
routes, same "server pre-renders `MAX_CATALOG_FIELDS` rows, a blank
`field_key` is skipped on submit" shape as Approval Flows' own step
builder, including the identical `[data-step-field]` JS).

**Two client-facing entry points, one shared service layer.** `/catalog`
(main app, under Records Authority, require_login) and the client
portal's own Request Something tab (open to every visitor, portal_require_
auth permitting -- see Client Portal below) both list active items and
post through `rain.modules.catalog.
service.submit_catalog_item` -- required-field validation, then `rain.
modules.tickets.service.create_ticket(source_catalog_item_id=item.id)`,
then `start_approval` if the item requires one. A submission is
therefore a completely ordinary ticket afterward: Platform Response
Rules, notifications, the activity feed, and export all see it exactly
like any other. `Ticket.source_catalog_item_id` (SET NULL on the item's
own deletion) backs a "Service Catalog request" row on the ticket detail
page, linked back to `/catalog/{key}` when the item is still active.

**`ApprovalFlow.notify_syslog_on_approval`** (off by default, a checkbox
on the flow form) raises a synthetic `SyslogEvent` (host `changes`,
program the ticket number) the moment a Change's last approval step
clears -- `tickets.service._emit_syslog_on_full_approval`, hooked into
`decide_approval_step` right where `overall_status` flips to `"approved"`.
Same synthetic-event convention as `Document.alert_on_change` above (a
self-generated event through the normal Event Promotion Policy
pipeline, not a second parallel notion of "event"), and the same reason
for a local, function-body import of `rules` there
(`rules.py` imports `tickets.service`, so a
top-level import back would be circular -- `create_ticket`'s own
`platform_events` import, in the same file, does the same thing).

**The produced ticket's description** is the submitted answers, in field
order, serialized per the item's `payload_format` -- `json`
(`json.dumps(..., indent=2)`) or `kv` (`key=value`, one per line, e.g.
`username=jdoe\ndomain=IBM\nuser_type=normal`). A blank optional answer
is pruned entirely rather than serialized as `null`/empty.

**The ticket detail page's Approval card isn't change-exclusive, even
though the Service Catalog admin form only ever offers approval for a
"change" service.** `ChangeApproval`/`ApprovalFlow` were already generic
over "the thing being approved" in the model layer (no `ticket_type`
constraint anywhere in that schema) -- only the ticket detail page's own
template and `tickets.router.ticket_detail` gated the Approval card and
its current-step/can-decide computation to `ticket_type == "change"`.
Both were widened to `ticket.ticket_type == "change" or ticket.approval`
(detail page) / off `ticket.approval` directly (current-step
computation), so *if* a ticket somehow has an approval attached despite
not being a change, it still shows up and is actionable there. In
practice nothing produces that combination any more: an incident or
vulnerability has no approval concept by design (a plain incident being
"pending approval" made no sense to a requester), so `admin/catalog_
item_form.html`'s Requires-approval/Approval-flow section is hidden
outright -- not just left unchecked -- for anything but "change" (the
same `#ticket_type` + `[data-change-fields]` show/hide the manual New
Ticket form already used for its own change-only fields), and `admin.
router`'s create/edit routes force requires_approval/approval_flow_id
back to false/None server-side whenever Produces isn't "change",
regardless of what a bypassed client might submit -- HTML's `hidden`
attribute only stops a field from being *seen*, not submitted. The
ticket-detail-page widening stays in place as the more general, still-
correct fix underneath; the admin form is just where the "changes
require approval, nothing else has one" *policy* actually lives now,
including the pre-existing rule that a "change" item must have
`requires_approval` and a flow selected to save at all.

**A field's value can come from a Document.** `ServiceCatalogField.
source_document_id`/`source_mode`/`source_expression`, resolved by
`catalog.service.resolve_field_source` against `rain.modules.documents.
textbody`'s already-existing text/Markdown/JSON body reader (the same
one the inline document editor and PDF export use) -- never a new way of
reading a document's content, just a new consumer of the existing one.
Three modes: `content` (the whole body -- each line an option, for a
select field, else the whole body as a prefill), `regex` (Python `re`,
`MULTILINE` only -- deliberately not also `DOTALL`, which would let a
greedy `.*` in a per-line pattern like `^(us-.*)$` cross newlines and
swallow the rest of the document as one match instead of one match per
line; caught live before shipping, see the fix's own comment in
`catalog.service`), and `jsonpath` (`jsonpath-ng`, body parsed as JSON
first). A select field gets every match/result as its option list
(falling back to the field's own static `select_options` if that comes
up empty); any other field type gets the first one as a prefilled but
still-editable default. Resolution is best-effort everywhere except the
admin's own Preview button: a missing document, a bad pattern, or
invalid JSON never breaks the end-user form (falls back to blank/static
config), but does surface as an inline error where an admin is actively
designing the field (`POST /admin/catalog/fields/preview`, same fetch-
and-inject-a-fragment shape as the Markdown body editor's own Preview
tab), so a mistake is visible before it's saved rather than only once a
requester hits it.

## Configuration bundles

`rain.modules.admin.config_bundle` backs Admin > Config Bundles: export
and import configuration -- never ticket/asset/document data -- as one
JSON file, for cloning a setup onto a different instance (or a fresh
tenant on the same one). Two independent bundle kinds, each importable
on its own with no dependency on the other:

- **Platform bundle** (`rain_platform_config`): everything genuinely
  instance-wide in this schema -- branding (instance name, accent
  color, font, logo, and the client portal's background image; all of
  these live in `control.global_config`, one set for the whole
  install, not per tenant -- see "Branding & runtime config" above),
  the SMTP relay, the LDAP and SAML provider configs (each a single
  row for the whole instance, pointed at one target tenant -- see
  `rain.modules.auth.ldap_config`'s own docstring for why RAIN doesn't
  support one directory per tenant), and syslog source routing rules.
- **Tenant bundle** (`rain_tenant_config`): one tenant's own asset
  types, custom fields, ticket statuses, groups and local users,
  notification channels, webhooks, approval flows, Event Promotion
  Policies, Platform Response Rules, and Service Catalog items.

Every cross-reference inside a bundle (a Platform Response Rule
action's notification channel, an approval step's group, a Service
Catalog item's approval flow, ...) is resolved by *name* at export
time and re-resolved by name again on import -- never a raw database
id, which means nothing on a different instance. Every entity is
upserted by its natural key (name/key/email) on import too, not
always-inserted, so re-importing the same (or an edited) bundle
updates the matching rows instead of duplicating them -- the one
exception is a local user, left untouched if an account with that
email already exists, so a re-import can never silently overwrite a
password/role an admin has since changed by hand.

Two things a bundle can't make portable, and doesn't try to: a
reference to actual data (a Platform Response Rule's "attach a
document" action, a Service Catalog field sourced from a specific
document) has no sane equivalent on a different tenant with no data
yet, so it's dropped at export time with a note in the bundle's own
`warnings` list explaining why, rather than either failing the whole
export or silently producing a rule that points at nothing. The ML
rule sidecar's trained runtime state (`TicketRuleState`) is excluded
outright -- it's a statistical model fit to this tenant's own observed
traffic, not configuration, and has no meaning transplanted elsewhere.

Secrets (the LDAP bind password, the SMTP password, a Slack/email
notification channel's config, a webhook's headers) are decrypted into
the bundle only when the exporting admin explicitly opts in
(`include_secrets`) -- off by default, the same "locked down unless
explicitly opted into" posture `portal_require_auth`/`portal_branded`
already use. Without it, the bundle stays structurally complete (every
other field present, plus a `"_redacted": true` marker) rather than
silently dropping those keys. This also sidesteps a real portability
problem on its own: `rain.core.crypto`'s Fernet key is derived from
`APP_SECRET_KEY`, a random secret generated fresh per install, so a
raw copy of another instance's ciphertext would be undecryptable
garbage regardless -- `include_secrets` decrypts on export and
re-encrypts with the *target* instance's own key on import, rather
than ever moving ciphertext across the boundary.

## Lessons from the first real Docker run

Everything above was verified by static checks only
(`py_compile`, importing the app from the source tree, rendering templates
against mock context) -- no Docker was available until partway through
hardening. Running the real stack surfaced four bugs no amount of that
static verification would have caught, all now fixed (plus a couple more
added since, from later real-Docker testing of subsequent features):

- **`op.create_sequence()`/`op.drop_sequence()` don't exist** on the
  Alembic version that actually gets installed (1.19.1) -- `AttributeError`
  inside the tenant migration. Fixed with
  `op.execute(CreateSequence(Sequence("...")))`, which (unlike raw SQL
  text) still respects `schema_translate_map`.
- **A lazy relationship touched via plain attribute access on a
  freshly-constructed, non-eager-loaded object** raises
  `sqlalchemy.exc.MissingGreenlet` under `AsyncSession` --
  `Asset.field_values` in the create-asset path. Query explicitly instead
  of relying on lazy-load; `selectinload(...)` at read time doesn't help
  a just-`Asset(...)`-constructed object that was never queried.
- **`env.py`'s `fileConfig(config.config_file_name)`** -- standard Alembic
  boilerplate -- applies `alembic.ini`'s `[logger_root] level = WARN`
  globally (and defaults to `disable_existing_loggers=True` separately).
  Between the two, the *first* migration at app/worker startup permanently
  silenced every `rain.*` logger for the rest of the process's life. This
  is why several bugs during hardening appeared to raise with nothing
  logged anywhere, at any layer, despite explicit `logger.exception()`
  calls -- fixed by not calling `fileConfig()` at all; Alembic's own
  migration-progress messages still log fine through normal propagation.
  `rain.cli`'s `uvicorn.run(..., log_config=None)` is defense in depth
  against the same footgun from uvicorn's own logging setup.
- **`schema_translate_map` applied to a single `Connection` checkout**
  (`session.connection(execution_options=...)`) rather than the engine
  doesn't survive a mid-session commit: the connection is released back to
  the pool, and the next statement on that session checks out a fresh one
  with no translate map, silently querying the wrong schema
  (`asyncpg.exceptions.UndefinedTableError`). Hit this via `db.refresh()`
  after commit (three call sites: ticket/document/syslog-event creation)
  and via a separate query after an earlier commit in the same session
  (`notify_ticket_created()` running right after `create_ticket()`
  commits). Fixed in `rain.db.base.tenant_session()` by binding
  `schema_translate_map` at the engine level
  (`engine.execution_options(...)`, a lightweight proxy over the same
  pool) instead, which survives any number of commits/reconnects within
  the session.

- **`op.bulk_insert()` and `op.add_column()`/`op.drop_column()` don't
  respect `schema_translate_map`** either, unlike `op.create_table()`/
  `op.create_index()`/`op.create_foreign_key()`/`op.execute(<DDL
  construct>)` which all do. Hit this twice back to back (migrations 0005
  and 0006): both emitted unqualified SQL (`INSERT INTO ticket_statuses
  ...`, `ALTER TABLE notification_channels ...`) and raised
  `UndefinedTableError` against a tenant schema with nothing of that name
  on the default search_path. Fixed by not trusting translate_map for
  these specific ops: `op.add_column()`/`op.drop_column()` take an
  explicit `schema=` kwarg (just pass it); for DML, read the schema off
  `op.get_bind().get_execution_options()["schema_translate_map"][None]`
  and fully-qualify your own raw SQL. This note is now baked into
  `migrations/tenant/script.py.mako`'s header comment, so it lands in
  every future revision file `alembic revision` generates -- don't delete
  it when trimming a new migration's boilerplate.

The third bug is the one worth internalizing: it made the other two look
far stranger than they were, because every debugging signal (logs,
exception handlers) had gone silent. **`rain.settings.Settings.debug`**
(env `DEBUG`, default `false`, wired through `docker-compose.yml`) exists
because of this -- when true, `rain.main`'s catch-all exception handler
puts the full traceback inline in the 500 response instead of a bare
"Internal Server Error", which is what made the remaining bugs tractable
to find at all. Never set it true against a real deployment; it includes
source paths, local variables, and SQL text in every unhandled-exception
response.

A few more, from a real GovCloud-style deployment attempt (external,
restricted Postgres; no Caddy; single container):

- **`WEB_FRONTEND` and `COMPOSE_PROFILES` disagreeing is a real, easy-to-
  hit footgun, not just a hypothetical `.env.example` warns about.**
  `WEB_FRONTEND` is never read by `docker-compose.yml` at all -- only
  `COMPOSE_PROFILES` decides whether `caddy` (`profiles: ["web-
  frontend"]`) actually starts. Confirmed live: `WEB_FRONTEND=false` with
  `COMPOSE_PROFILES` still containing `web-frontend` starts Caddy anyway,
  which then fails to resolve/get a cert for a domain nothing was
  actually supposed to be serving. `bootstrap`'s Caddy question now sets
  both together in one place instead of leaving them to be hand-kept-in-
  sync.
- **`POSTGRES_URL` (the `.env`/Compose-facing name) and `DATABASE_URL`
  (what `rain.settings.Settings` actually reads) being two different
  names was fine as long as `docker-compose.yml` was the one translating
  between them, but broke down the moment `docker run --env-file .env`
  bypassed Compose entirely** -- `.env` has no `DATABASE_URL` line at
  all, only `POSTGRES_URL`, so the app fell back to its own
  `localhost`-pointing default instead of the external Postgres actually
  configured. Fixed at the `Settings` level instead of only the Compose
  level: a `model_validator` applies the same `POSTGRES_URL` fallback
  `docker-compose.yml`'s `${POSTGRES_URL:-...}` already did, keyed off
  whether `DATABASE_URL` was ever explicitly provided
  (`"database_url" not in self.model_fields_set`) so an explicit
  `DATABASE_URL` -- the normal Compose path, which always sets one --
  still wins outright.
- **"bind failed: port is already allocated" on `SYSLOG_PORT` wasn't a
  bug in publishing the same host port for both tcp and udp** (confirmed
  live: one container publishing `-p 5514:5514/tcp -p 5514:5514/udp`
  together works fine) -- **it was this repo's own separate `docker
  compose` stack already running and holding that port**, from testing
  the normal multi-container path earlier in the same session. Any two
  RAIN instances (Compose-based or a bare `docker run`) sharing
  `APP_PORT`/`SYSLOG_PORT` hit this the same way; it's an ordinary Docker
  port conflict, not specific to any one deployment shape. `bootstrap`'s
  final single-container instructions now say so explicitly rather than
  leaving it to look like a broken feature.

## Pagination & tenant defaults

`rain.core.pagination.paginate(db, stmt, page=..., page_size=...)` is the
one offset-pagination helper every list screen in the app uses (see its
own module docstring); `page_size` defaults to `DEFAULT_PAGE_SIZE` (25)
when a caller doesn't pass one. `TenantConfig.DEFAULTS["default_page_size"]`
(`rain.core.tenant_config`, importing `DEFAULT_PAGE_SIZE` from
`rain.core.pagination` -- no cycle, `pagination.py` itself only imports
SQLAlchemy) makes that overridable per tenant: every router whose
`paginate()` call reads from a `tenant_db` session now does `page_size =
await get_tenant_config(tenant_db, "default_page_size")` first and passes
it through -- Tickets (table, custom fields, Event Promotion Policies,
Platform Response Rules), Assets (list, types, fields), Documents, and the
client portal's own shareable-documents/documents tabs (`rain.modules.
portal.router.portal_form`, which resolves a `tenant_session` for the
tenant the URL names, same as any of these). Saved from Admin > Branding >
"Tenant defaults" (`admin.router.branding_defaults_submit`), a fixed
dropdown (`PAGE_SIZE_CHOICES = [10, 25, 50, 100, 200]`) rather than a free-
typed number -- every caller passes this straight through as a SQL
`LIMIT`, so an admin fat-fingering an extra zero would turn one page load
into a real, self-inflicted performance problem; a submitted value is
clamped to the nearest allowed choice rather than rejected outright,
consistent with how a stale/tampered field elsewhere in this app degrades
to "closest sane thing" instead of hard-failing a whole form save over it.

Deliberately **not** applied to the handful of `paginate()` callers that
read from `control_session()` instead of a tenant schema -- Admin >
Tenants, platform Users, and Syslog Sources (`admin.router.tenants_list`/
`tenants_create`/`users_list`/`syslog_sources_list`) -- each commented at
its own call site. These are platform-level lists with no single tenant's
config to read in the first place; `TenantConfig` itself only resolves
against a tenant schema's own connection, so calling `get_tenant_config`
against a `control_session()` connection wouldn't just be semantically
wrong, it would fail outright (no `tenant_config` table in `public`).

**Row density** (the Normal/Condensed toggle, `[data-density-toggle]` in
`app.js`) is an unrelated, purely client-side concern -- a
`.density-condensed` class toggled on whichever single element opts in
via `[data-density-target]`, persisted in `localStorage` (one shared
key, `rain-density`, across every page that offers it -- originally
tickets-scoped, generalized once the Events tab got its own toggle) the
same way the sidebar's own collapsed state is. It changes how tightly
the rows *already on the page* are drawn, not how many rows that page
has -- that's what tenant page_size above governs. The toggle logic
itself doesn't know or care what it's condensing; `.tickets-table`
(list.html) and `.live-feed` (live.html) each carry their own CSS for
what "condensed" tightens on that specific layout (a table's own
`td` padding vs. a `.live-row`'s already-tighter grid padding).

**Custom JS injection.** Two more `TenantConfig.DEFAULTS` keys,
`app_custom_js` and `portal_custom_js` -- raw HTML/JS an admin pastes in
(Admin > Branding > "Tenant defaults") for a third-party snippet
(analytics, a chat widget) that needs to run as a real `<script>` tag,
not something a sanitizer could preserve. Both are rendered with `|safe`
in `base.html` -- a deliberate, explicit trust boundary (a tenant admin
already has far more reach than this: webhooks that can target this
app's own internal network, SSO configuration, every user's role), not
an oversight in an otherwise-autoescaped app. Two keys, not one, because
the blast radius differs: `app_custom_js` runs in the *authenticated*
app, on every signed-in user's own session; `portal_custom_js` runs on
the public, often-anonymous incident portal. Neither should imply the
other is safe to reuse for, so a tenant opts into each independently.

Getting each to the right surface *and only* that surface leans on how
the two already differ structurally, rather than a new mechanism:

- `app_custom_js`: fetched by `rain.web.nav._app_custom_js` and returned
  as part of `build_nav_context(ctx)`'s own dict -- every authenticated
  app route already calls this and spreads its result (`**nav`) into the
  template context, so this needed no changes anywhere else. Rendered in
  `base.html` right before `</body>`, guarded by `{% if app_custom_js is
  defined and app_custom_js %}`.
- `portal_custom_js`: fetched once in `rain.modules.portal.router._
  resolve_portal_tenant_and_flags` (already batches `portal_require_auth`/
  `portal_branded` the same way) and threaded explicitly into the three
  portal routes that render a full page (`portal_form`, `portal_catalog_
  form`, `portal_catalog_submit`'s error re-render) -- `portal_ticket_
  timeline` doesn't need it, since that one returns a fragment injected
  via `innerHTML` into an already-loaded portal page, not a fresh
  `base.html` render. Rendered in `base.html`'s `{% else %}` branch (the
  `content-standalone` shell login/setup/errors/portal all share), same
  `is defined` guard.

The `is defined` guard on both is what keeps this scoped correctly
without an explicit "which surface is this?" flag: `build_nav_context`
is never called by portal/login/setup routes, and those routes never
pass `portal_custom_js` either, so each variable is only ever truthy on
the one surface that's supposed to populate it -- a route that forgets
to thread one through just gets no injected script there, never someone
else's.
