# RAIN architecture

This is the living design doc for RAIN, kept in-repo so Milestones 2 and 3
extend the same foundation rather than re-deriving it. See the repo root
[`README.md`](../README.md) for the quickstart.

## Containers

| Service | Image basis | Role |
|---|---|---|
| `caddy` | `caddy:2-alpine` | Reverse proxy + automatic HTTPS. Only container exposing 80/443. |
| `app` | `python:3.12-alpine`, multi-stage | FastAPI web app (Uvicorn), server-rendered UI. |
| `worker` | same image as `app`, different command | Background process -- a placeholder in Milestone 1, becomes the syslog listener/rule engine/notifier in Milestone 2. |
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
  `roles`, `global_config`, `auth_providers`, `audit_log`.
- `tenant_<slug>` schema per tenant: `asset_types`, `custom_fields`,
  `assets`, `asset_field_values`, `export_profiles`, `sync_connections`,
  `sync_runs`, `audit_log`. Future milestones add their tables here too.
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
would need to change to adopt it.

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

## Roadmap

- **Milestone 2 -- Ticketing**: `worker` becomes a syslog listener (syslog-ng
  pushes to it as a destination) → per-tenant routing via a
  `control.syslog_source_map` (host/program → tenant) → live viewer over
  WebSocket using Postgres `LISTEN`/`NOTIFY` for fan-out → regex rule
  editor (`ticket_rules`) auto-promoting events into `INC-xxxx`/`VULN-xxxx`
  tickets (per-tenant Postgres sequences) → email (`aiosmtplib`)/Slack
  webhook notifications → CSV/JSON export reusing the Asset Registry's
  export-profile mechanism.
- **Milestone 3 -- Documents**: `DOC-xxxx` entries, local-volume storage
  behind a small swappable-for-S3 storage abstraction, polymorphic
  `document_links(document_id, linked_type[asset|ticket], linked_id)`.
- **Future -- LLM search hook**: pgvector is already installed; add an
  `embeddings` table and a `SearchProvider` interface once a concrete
  model/API is chosen.
