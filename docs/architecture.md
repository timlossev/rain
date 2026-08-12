# RAIN architecture

This is the living design doc for RAIN, kept in-repo so future work extends
the same foundation rather than re-deriving it. See the repo root
[`README.md`](../README.md) for the quickstart.

## Containers

| Service | Image basis | Role |
|---|---|---|
| `caddy` | `caddy:2-alpine` | Reverse proxy + automatic HTTPS. Only container exposing 80/443. |
| `app` | `python:3.12-alpine`, multi-stage | FastAPI web app (Uvicorn), server-rendered UI. |
| `worker` | same image as `app`, different command | The syslog listener (TCP+UDP), rule engine, notifier, and retention sweeper -- see Ticketing below. Publishes its own port (`SYSLOG_PORT`, default 5514) directly, bypassing Caddy since this is raw syslog, not HTTP. |
| `db` | `postgres:16-alpine` + pgvector compiled in | One Postgres instance; `control` schema plus one `tenant_<slug>` schema per tenant. |

Only two inputs are needed outside the database: `POSTGRES_PASSWORD` and
`APP_SECRET_KEY` (session-cookie signing + the Fernet key that encrypts
config-at-rest, e.g. cloud-sync credentials). `bootstrap.py` /
`bootstrap.ps1` / `bootstrap.sh` generate both into `.env` on first run.
`RAIN_DOMAIN` is optional and defaults to `localhost` (Caddy's internal CA).
Everything else lives in Postgres and is edited at runtime through the
setup wizard and Admin UI.

## Multi-tenancy: schema-per-tenant

- `control` schema (always present): `tenants`, `users`, `sessions`,
  `roles`, `global_config`, `auth_providers`, `syslog_source_map`,
  `audit_log`.
- `tenant_<slug>` schema per tenant: `asset_types`, `custom_fields`,
  `assets`, `asset_field_values`, `export_profiles`, `sync_connections`,
  `sync_runs`, `tenant_config`, `syslog_events`, `ticket_rules`, `tickets`,
  `ticket_comments`, `notification_channels`, `documents`, `document_links`,
  `audit_log`.
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

Local email+password (Argon2, `argon2-cffi`) is the only functional
provider in Milestone 1. Sessions are DB-backed (`control.sessions`): the
cookie holds an opaque token, only its sha256 hash is stored, revocation is
a row delete. `control.auth_providers` already has disabled `oidc`/`saml`/
`ldap` rows -- the hooks the spec asked for -- ready for a future release
to implement `authenticate_<provider>()` alongside
`rain.modules.auth.provider.authenticate_local`.

Roles come from a `control.roles` table (not a hardcoded enum), seeded with
exactly `internal_admin` (platform operator, all tenants) and `client`
(full control scoped to their own tenant) -- literally the two personas the
spec calls for, but structured so a finer-grained role is an admin action
later, not a migration.

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
- Cloud sync scaffolding: `SyncProvider` protocol with `AWSProvider` /
  `AzureProvider` stubs (`rain.modules.assets.sync`) -- connection CRUD and
  config validation work now, `discover_assets()` raises "coming in the
  next release" until implemented. Credentials are Fernet-encrypted at
  rest, keyed from `APP_SECRET_KEY`.

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
(`notification_channels`, config Fernet-encrypted same as
`sync_connections`).

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
protocol (`save`/`read`/`delete` on an opaque string key) with one
implementation, `LocalStorageBackend`, writing under
`{uploads_dir}/documents/<tenant_schema>/<random-token>-<filename>` on the
shared `rain_uploads` volume. Swapping in S3 later means implementing the
same three methods and changing `get_storage()` -- nothing in the router or
service layer touches the filesystem directly. `make_storage_key()` both
namespaces by tenant and strips any path components from the uploaded
filename (`Path(name).name`), so a filename like `../../etc/passwd` can't
escape the tenant's subtree.

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

## Roadmap

- **LLM search hook**: pgvector is already installed; add an `embeddings`
  table and a `SearchProvider` interface once a concrete model/API is
  chosen. Natural to wire into the Document Repository first (index
  `documents` content) and extend to tickets/assets from there.
- **Cloud sync**: implement `AWSProvider`/`AzureProvider.discover_assets()`
  (currently `NotImplementedError` stubs -- see Asset Registry above).
- **OIDC/SAML/LDAP**: `control.auth_providers` rows already exist,
  disabled -- implement `authenticate_<provider>()` alongside
  `rain.modules.auth.provider.authenticate_local`.
