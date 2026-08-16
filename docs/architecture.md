# RAIN architecture

This is the living design doc for RAIN, kept in-repo so future work extends
the same foundation rather than re-deriving it. See the repo root
[`README.md`](../README.md) for the quickstart.

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
`bootstrap.ps1` / `bootstrap.sh` generate both into `.env` on first run.
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
mode, document uploads (and the branding logo, which stays local-disk-
only regardless of `S3_BUCKET` -- see `rain.modules.documents.storage`'s
docstring) live in the container's own writable layer with no volume
behind it at all, gone the next time the container is recreated -- an
explicit, documented trade-off for genuine single-container simplicity,
not an oversight.

## Multi-tenancy: schema-per-tenant

- `control` schema (always present): `tenants`, `users`, `sessions`,
  `roles`, `global_config`, `auth_providers`, `syslog_source_map`,
  `audit_log`.
- `tenant_<slug>` schema per tenant: `asset_types`, `custom_fields`,
  `assets`, `asset_field_values`, `export_profiles`, `tenant_config`,
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

Roles come from a `control.roles` table (not a hardcoded enum), seeded with
`internal_admin` (platform operator, all tenants, every setting),
`client` (full control scoped to their own tenant, no admin functions),
and `client_admin` (pinned to one tenant exactly like `client` --
`CurrentUser.is_internal_admin` is false for both -- but also passes
`rain.core.rbac.require_admin`, giving them admin rights over that one
tenant's own tenant-scoped settings: Ticket Statuses, Notification
Channels, Groups, Approval Flows, Webhooks, Event Promotion Policies,
Correlation Rules, Platform Response Rules). `require_admin` accepts
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
practice the surface Milestone 1 needed -- nav expand/collapse, reloading a
custom-fields fragment when the asset type changes, confirm-before-delete
-- is about 70 lines of vanilla JS, and the visual design is one hand-written
CSS file using custom properties for the accent color. Dropping the three
libraries removes an entire JS supply chain (nothing to download at image
build time, nothing to patch for CVEs, no version pinning to maintain) at
no real cost to the UI. If a future milestone's interactions outgrow plain
`fetch()` calls, htmx is a single `<script>` tag away and nothing here
would need to change to adopt it. Milestone 2's one addition,
`static/js/live.js`, follows the same rule: a plain `WebSocket` client with
no library, kept in its own file (loaded only on the live-viewer page via
`{% block extra_scripts %}`) rather than bloating the shared `app.js`.

## Asset Registry (Milestone 1, full scope)

- `asset_types` / `custom_fields` (EAV field definitions, `asset_type_id`
  nullable = applies to every type) / `assets` / `asset_field_values`.
- CSV/JSON import: upload → column-to-field mapping (auto-suggested by
  header name) → commit, upserting by `external_id` when present
  (`rain.modules.assets.importer`).
- CSV/JSON export: ad-hoc or saved `export_profiles` -- pick columns,
  headers, and order (`rain.modules.assets.exporter`).

## Ticketing (Milestone 2, full scope)

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

**Rule engine + tickets.** Each persisted event is checked against that
tenant's active `ticket_rules` (regex on `message`/`host`/`program`,
evaluated in `sort_order`, first match wins --
`rain.modules.tickets.rules`). A match creates a `Ticket` via
`rain.modules.tickets.service.create_ticket`, which numbers it
`INC-000123` / `VULN-000045` from a real Postgres sequence
(`inc_number_seq` / `vuln_number_seq`, one pair per tenant schema, allocated
through SQLAlchemy's `Sequence(...).next_value()` so `schema_translate_map`
resolves it to the right schema -- raw `nextval('name')` SQL text would
not, since translation only applies to compiled schema-item constructs,
not textual SQL). The same manual "Promote to Incident/Vulnerability"
buttons in the live viewer hit `GET /tickets/new?source_event_id=...`,
which pre-fills the form and suggests an asset match by `external_id`.

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
*after* a ticket already exists (auto-promoted or manual), and every
active, pattern-matching rule fires, not just the first (unlike the
single-event rule engine above). Actions: notify Slack/email (reusing
`NotificationChannel`), call a webhook, attach a document or asset,
mark the ticket problematic, or add a watcher (email or system user,
see above). Every firing -- and each action's individual outcome, even
a failed one -- is logged to `platform_event_triggers` and the
ticket's own activity feed, so a failed Slack post doesn't hide the
fact the rule matched.

**Escalation.** A per-tenant "escalation webhook" (one `WebhookConfig`,
picked on Admin > Branding next to the portal's own settings, stored as
`tenant_config["escalation_webhook_id"]`) backs a manual "Escalate"
button shown on every ticket detail page -- and next to a signed-in
portal visitor's own tickets -- whenever a tenant has one configured,
absent otherwise. Unlike a Platform Response Rule's webhook action,
this isn't pattern-matched or automatic: `rain.modules.tickets.service.
escalate_ticket` fires it for one ticket, on demand, logged to that
ticket's activity feed the same way a rule firing is.

**Correlation Rules.** `rain.modules.tickets.correlation`, evaluated
alongside the single-event rule engine above, once per persisted event.
`CorrelationRule.rule_type` picks one of two ways to decide "this is
worth a ticket": `threshold` counts matching events in a trailing
window (a plain bounded SQL query re-run on each new event -- no
streaming engine, since the new event is the only thing that can ever
push the count over the line); `ml_anomaly` scores each matching event
against a per rule+group_key online model (`river.anomaly.HalfSpaceTrees`,
trained on severity/message-length/hour-of-day -- deliberately small
and numeric, not an NLP pass over the message) and fires once the score
clears a threshold, after a warm-up count of events. A model's pickled
state persists on `CorrelationRuleState.ml_model`, read/written under
`SELECT ... FOR UPDATE` since scoring-then-training is a read-modify-
write, not a single atomic statement the way the threshold path's
last-fired timestamp bump is; the row is only ever written with bytes
this module just pickled itself, never with anything from a request, so
unpickling it back isn't a deserialization-of-untrusted-input concern.
Both rule types share the same cooldown/group-by/asset-link mechanics
and the same `New rule` modal, split into "Simple repetition" / "ML
anomalies" tabs.

**Export.** `GET/POST /tickets/export/run` -- fixed-column CSV/JSON
(tickets don't carry custom fields the way assets do, so this skips the
Asset Registry exporter's configurable-column picker).

**Document linking** (the ticketing spec's "link to a document repository
as a knowledge base") is live -- see Document Repository below.

### A routing bug worth knowing about

While wiring `/tickets/live` in next to `/tickets/{ticket_id}`, a
pre-existing bug from Milestone 1 surfaced: FastAPI/Starlette match routes
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
routes in future milestones.

## Document Repository (Milestone 3, full scope)

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

Branding logos (`rain.web.uploads`) and the CSV/JSON import stash stay on
local disk regardless of `s3_bucket` -- logos are served straight off the
local static mount (`/media/branding`), which an S3 object can't be
without a signed-URL redirect this app doesn't have, and the import stash
is transient by design (gone once the import finishes). Both are small/
short-lived enough that this doesn't undercut S3's actual purpose here:
document bodies, which can be large and numerous, are what "eliminate the
uploads volume" is actually about.

**Access control.** Documents are *never* served through the static file
mount. `/media` was previously mounted over the whole `uploads_dir` --
harmless while it only held branding logos, but Milestone 3 also uses that
volume for tenant documents and the CSV/JSON import stash, both of which
must stay tenant-scoped and authenticated. Fixed by mounting only
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
`doc_number`/`title`/`description` respectively, weighted (`setweight`,
number/title `'A'`, description `'B'`), GIN-indexed. Metadata only, not
a document's file body -- indexing arbitrary uploaded file content is a
bigger feature this doesn't attempt.

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

**Reserved for later.** `control` enables the `vector` extension once,
database-wide (`CREATE EXTENSION IF NOT EXISTS vector`, control migration
0006 -- extensions are per-database, not per-schema, so this doesn't
repeat per tenant); `tickets.embedding`/`documents.embedding`
(`pgvector.sqlalchemy.Vector(1536)`, tenant migration 0023) are nullable
and completely unpopulated today. The dimension (1536) matches common
embedding APIs' output size as a reasonable placeholder, not a
commitment to a specific provider -- see the Roadmap entry below.

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
tenant. `_resolve_portal_access` is the single choke point both the
GET and POST route share for tenant resolution and the wrong-tenant/
require-auth gate, so the two can't silently drift on what's allowed
through.

**Gating.** Two `TenantConfig` flags an admin sets on Admin > Branding:
`portal_require_auth` (off: anyone with the link can file anonymously,
the ticket records "an unauthenticated user" as the reporter) and
`portal_branded` (off: a plain, unaccented page showing only the
tenant's own name, for a portal shared outside the organization). A
signed-in visitor whose own tenant isn't the one in the URL is always
turned away with a plain 403, regardless of `portal_require_auth` --
that flag controls whether *an* account is required, not whether an
account for a *different* tenant is accepted.

**Two views, one template.** An anonymous visitor gets exactly the
original bare-bones form (new ticket +, once signed in, "Tickets
reported by me") plus "Today's events" -- every visitor's page,
regardless of sign-in status, since it's tenant-wide operational
information (`rain.modules.calendar.service.list_entries_due_today`,
reusing the month-grid view's own occurrence math). A signed-in visitor
additionally gets a wider layout (`.portal-shell.portal-authenticated`)
with a search bar and three tabs -- Tickets, Approvals (backed by
`rain.modules.tickets.service.list_tickets_pending_approval_for`, the
same eligibility rule `is_eligible_approver` uses, evaluated as a set
query), and Documents. `.content-standalone` (base.html's `<main>` for
login/setup/portal alike) is a centered flexbox; overridden to normal
top-down block flow specifically when a `.portal-shell` is present
(`.content-standalone:has(.portal-shell)`, same `:has()` technique as
the sidebar-collapse override) so switching between tabs of different
heights doesn't recenter -- and visibly jump -- the whole page.

**Escalate.** Next to a signed-in visitor's own tickets in the Tickets
tab, whenever the tenant has an escalation webhook configured -- same
feature as the ticket detail page's own Escalate button, see
Ticketing's Escalation section above. Posts to the same
`/tickets/{id}/escalate` route `require_login` already gates, with a
`next` field so it returns to the portal instead of a ticket detail
page this visitor might not even be allowed to open on its own
(`portal_require_auth` off doesn't imply this visitor can view
`/tickets/<n>` -- that's still `require_login`).

## Lessons from the first real Docker run

Everything above was verified through Milestone 3 by static checks only
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

## Roadmap

- **Semantic/vector search**: keyword search (Postgres full-text) is live
  today -- see the Search section above. `tickets.embedding`/`documents.
  embedding` (pgvector, enabled) are reserved but unpopulated; this needs
  a concrete embedding model/API chosen and a backfill + a `SearchProvider`
  interface, not a schema change.
- **Multiple LDAP/SAML sources**: currently one of each, syncing/signing
  into exactly one target tenant, instance-wide.
- **Service catalog**: a tenant-defined catalog of requestable services/
  items (e.g. "new laptop", "VPN access"), each optionally routed through
  an approval flow -- the natural next consumer of the same Approval Flow
  machinery Change tickets already use (`rain.modules.tickets.service`'s
  `ApprovalFlow`/`ChangeApproval` machinery is already generic over "the
  thing being approved" in spirit, just not yet wired to anything but a
  change ticket).
