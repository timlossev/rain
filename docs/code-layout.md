# Code layout & how to change things

Where things live, the conventions the codebase already follows, and a
practical walkthrough for the kinds of changes you'll make most often.
`docs/architecture.md` is the *why* behind the bigger design decisions;
this doc is the *where* and *how*, for getting oriented and making a
change that fits.

## Repository layout

```
docker-compose.yml, docker-compose.minimal.yml, Caddyfile, db/Dockerfile   -- infra
charts/rain/                                    -- Helm chart, same deployment shapes as the two compose files
backend/
  Dockerfile, pyproject.toml
  alembic.ini, migrations/{control,tenant}/    -- two independent migration chains
  src/rain/
    main.py             -- app assembly: registers every module's router + nav
    settings.py          -- the only place env vars are read
    cli.py                -- rain-web / rain-worker entry points
    worker_runtime.py      -- shared services (syslog listener, rule engine, ...) the worker or an embedded app process runs
    db/                  -- models, engine/session, tenant provisioning
    core/                 -- security, RBAC, tenancy resolution, config stores, nav registry, pagination
    modules/{setup,auth,admin,assets,tickets,catalog,calendar,documents,home,portal,webhooks,search}/  -- one router+service per feature area
    web/                   -- Jinja2 templates, hand-written CSS/JS, PDF rendering
  tests/
docs/
  architecture.md            -- design rationale, deployment lessons, deep dives
  database-schema.md          -- every table, columns, relationships
  code-layout.md                -- this file
  user-guide.md                  -- task-oriented, organized by the app's own sidebar
  itsm-controls-mapping.md        -- the compliance-control analysis behind the project
  eucs-compliance-assessment.md    -- scope-honest assessment of RAIN against EUCS
  compliance-templates/             -- starter tenant-config-bundle JSON files (Risk Register, Subprocessor Register, PIV/CAC Card issuance, Software License, Cloud Environment, Encryption Key/Certificate, System Interconnection, Contractor Access, Data Inventory, POA&M tracking fields)
```

## Backend module map

Every feature area under `modules/` follows the same shape, though not
every module needs every file:

- **`router.py`** -- FastAPI routes. Thin: pulls the request apart,
  calls `service.py`, renders a template or redirects. No business
  logic here beyond request/response shaping.
- **`service.py`** -- the actual logic, as plain async functions taking
  an `AsyncSession` as their first argument. This is what a unit test
  should call directly, not the router.
- **`schemas.py`** -- shared constants/small types (allowed enums like
  `TICKET_TYPES`/`SEVERITIES`, a `FieldType` set, request/response
  shapes that don't belong in the DB model). Not every module has one.
- **`nav.py`** -- registers this module's sidebar entry/entries with
  `rain.core.nav_registry`, imported once (for the side effect) in
  `main.py`. A count badge next to a nav item is a small async function
  passed as `count_provider`.

Module by module:

| Module | Owns |
|---|---|
| `setup` | First-run wizard (instance name, first tenant, first admin). |
| `auth` | Local/LDAP/SAML login, logout, password reset, LDAP sync, SAML SSO flow. |
| `admin` | Branding, Tenants, Users, Auth Providers, SMTP Relay, Syslog Listener, Config Bundles (Platform Administration); Groups, Ticket Statuses, Notification Channels, Approval Flows, Webhooks, Asset Types, Field Pack import, Tenant defaults, Config Bundles (Tenant Administration). One large `router.py` -- see its own section headers. `config_bundle.py` holds the export/import logic for both bundle kinds, kept separate from the router for the same reason every other module's `service.py` is. |
| `assets` | Asset Registry: types, custom fields, CRUD, import/export. |
| `tickets` | The biggest module by far -- ticket CRUD, the table/Kanban/board views, Event Promotion Policies (`rules.py`), Platform Response Rules (`platform_events.py`), root cause assistance (`rootcause.py`), the live syslog viewer (`live.py`, `live_bus.py`), syslog parsing/format detection (`syslog_parser.py`, `event_formats.py`), tenant-to-event routing (`routing.py`), notifications, import/export. |
| `catalog` | Service Catalog: requestable forms that produce a ticket on submission. |
| `calendar` | Per-tenant calendar, recurrence math (`recurrence.py`), the syslog-bridge sweep (`sweep.py`), `.ics` export/import. |
| `documents` | Document repository: storage abstraction (`storage.py`), Markdown/text rendering (`textbody.py`), webhook auto-population, sharing/landing-page flags. |
| `home` | The landing page -- small: one route, one nav entry. |
| `portal` | The public, often-anonymous client portal (`/portal/<slug>`). |
| `webhooks` | Centrally-configured outbound webhooks, called by rules/documents/escalation. |
| `search` | Global full-text search + the `INC-000001`-style number shortcut. |

### Cross-cutting layers

- **`core/`** -- things every module leans on: `rbac.py` (role checks),
  `tenancy.py` (resolving which tenant/user a request belongs to),
  `security.py`/`crypto.py` (password hashing, Fernet encryption),
  `config_store.py` (platform-wide `global_config`, cached) vs.
  `tenant_config.py` (per-tenant `tenant_config`, read fresh),
  `nav_registry.py` (the sidebar tree), `pagination.py` (the one
  `paginate()` helper every list screen uses), `url_safety.py` (SSRF
  guard for outbound webhook/Slack calls), `export_columns.py`/
  `field_pack.py`/`user_names.py`/`xlsx_export.py` (shared helpers for
  export screens and the ticket field-pack importer).
- **`db/`** -- `control_models.py`/`tenant_models.py` (see
  `docs/database-schema.md`), `base.py` (engine/session setup, the
  `schema_translate_map` mechanism), `provisioning.py` (creating a new
  tenant schema), `migrate.py` (running both Alembic chains at
  startup).
- **`web/`** -- `templating.py` (the shared Jinja environment),
  `pdf.py` (xhtml2pdf rendering, with its own `link_callback` SSRF/
  path-traversal guard -- see `test_pdf_export.py`), `nav.py`
  (`build_nav_context`, called by nearly every authenticated route),
  `uploads.py` (branding asset persistence), `safe_redirect.py` (the
  `next=` open-redirect guard), `static/css/app.css` + `static/js/
  app.js` (one file each for the whole app -- no bundler, no
  framework), `templates/` (one directory per module, plus shared
  partials at the top level: `base.html`, `_search_picker.html`,
  `_pagination.html`, `_help.html`).

### App assembly

`main.py`'s `lifespan` does two things in order: import each module's
`nav` submodule (for its `nav_registry.register(...)` side effect --
`# noqa: F401`, nothing from the import is used directly), then import
and `app.include_router(...)` each module's router. A module that's
missing from *both* lists doesn't exist in the running app, no matter
how correct its own code is -- this is the one step it's easy to
forget when adding a whole new module (see the walkthrough below).

## Frontend conventions

Server-rendered Jinja2, no SPA framework, no build step. A few patterns
that recur enough to know before you add to them:

- **Shared modals live in `base.html`**, not on the one page that
  first needed them, whenever more than one surface should show the
  same window -- the root-cause preview, the escalation result, and
  the full-syslog-event preview (shared between the Events tab and a
  ticket's own "Source event" link) all do this. A modal opts into
  Escape/backdrop-click/close-button handling just by carrying
  `data-modal` on its `.modal-overlay`; `app.js`'s generic plumbing
  wires the rest.
- **`app.js` is one file, one `DOMContentLoaded` listener, sequential
  blocks** -- each self-contained, scoped to elements it finds via
  `document.querySelectorAll(...)`, a no-op on any page that doesn't
  have that element. `live.js` (the syslog live-feed WebSocket client)
  is the one separate script, loaded only on `/tickets/live` via
  `{% block extra_scripts %}`.
- **A `[data-foo]` attribute, not a class, is what JS hooks into** --
  classes are for CSS. Keeps a template free to restyle an element
  without touching the script that drives it, and vice versa.
- **Shared filter bars/macros get their own partial** once two pages
  need the same one -- `tickets/_filter_bar.html` (the table view and
  Kanban board's filter bar) is the pattern to copy: a macro file,
  imported `with context`, so both callers can't drift apart on what a
  filter means.
- **A tenant-configurable setting is a `tenant_config` key**, not a new
  column, when it's a single scalar value (a label, a flag, a page
  size) -- see "Add a tenant-wide setting" below.

## Testing: what's there and what isn't

`backend/tests/` is a real but still-not-exhaustive suite -- worth an
honest read before assuming it catches something:

- **~150 fast, DB-free tests** (`pytest`, no setup needed) covering
  pure functions: syslog/CEF/JSON/kv parsing, tag/CSV/field-pack
  parsing, calendar recurrence's occurrence math (including the Jan
  31 quarterly -> Apr 30 -> Jul 31 clamp-and-recover case), Platform
  Response Rules' regex matching, document tag/diff/webhook-JSON
  helpers, root-cause's span formatter, a handful of security-
  regression cases (CSV formula injection, markdown sanitization, SSRF
  URL checks, PDF `link_callback` path guards, search snippet
  escaping), and Service Catalog payload rendering.
- **18 integration tests** (`test_integration.py`, skipped unless
  `TEST_DATABASE_URL` is set) against a real Postgres -- tenant
  provisioning, asset CRUD, ticket numbering + rule promotion, syslog
  routing, document numbering/linking, custom fields, tags/search, a
  Platform Response Rule firing its actions end to end (and an
  inactive/non-matching one correctly not firing), escalation posting
  its webhook response as both a field-change line and a comment
  (with the response-body truncation cap), root-cause's auto comment
  plus a close-triggered Platform Response Rule both firing once on a
  status transition into `closed`, never again on a later closed ->
  closed move, a tenant configuration bundle's hardest interdependent
  path (a group, a local user, an approval flow step, an event policy
  and a Service Catalog item all referencing each other by name)
  round-tripping through JSON onto a *different* tenant, a platform
  bundle redacting a secret by default while still round-tripping it
  with `include_secrets`, `list_assignable_users`' tenant/active
  scoping (Kanban's "group by assignee" columns) against another
  tenant's user and a deactivated one of this tenant's own, the
  Documents list's tag filter (exact membership, not a substring match)
  plus its calendar-link flag lookup, the Documents Kanban board's
  retag (a targeted swap that merges rather than duplicates onto a tag
  already carried under different casing) and owner assignment, the
  overdue-review filter (an untracked document never counts as
  overdue) plus acknowledgment's upsert-not-accumulate semantics, and
  an assignable acknowledgment requirement end to end -- a group
  resolving to its members, each showing up on the client portal's
  pending-acknowledgment query, a document-triggered Platform Response
  Rule firing (with a ticket-only action correctly skipping itself
  rather than erroring), acknowledging clearing just that one member's
  pending status, and re-requesting putting an already-acknowledged
  member back on the list. Broad strokes, not deep: each is one
  scenario, not a sweep of edge cases.

  All 16 have actually been run against a real Postgres (a local
  `docker compose up` stack, once one was available this session for
  the first time) -- not just reviewed, the state every one of them
  was in before. That first real run only got 3 of 15 tests to
  complete at all: `asyncio_mode = "auto"` alone hands every async
  test function pytest-asyncio's own function-scoped event loop by
  default, but `rain.db.base.get_engine()` caches one `AsyncEngine`
  (and its asyncpg connection pool) at module-global scope and
  `_clean_slate` is a module-scoped fixture -- both assume every test
  in the module shares one loop. Fixed with
  `asyncio_default_fixture_loop_scope = "module"` (`pyproject.toml`)
  plus an explicit `pytest.mark.asyncio(loop_scope="module")` on the
  module (the ini option alone only reaches fixtures, not a plain
  `async def test_*`, in this pytest-asyncio version). Getting the rest
  green surfaced six more real, previously-invisible bugs, three in
  the tests themselves (two stale assertions -- `client_admin`
  missing from the seeded-roles check, `resolve_tenant_for_event`
  returning a `RoutingResult` wrapper the test never accounted for --
  and one that asserted a document's cascade-deleted `CalendarEntry`
  was gone by calling `session.get()`, which checks the identity map
  before the database and so returned the same still-cached Python
  object regardless of what actually happened server-side) and two in
  `config_bundle.py` itself (a `NotificationChannel` upsert flushing a
  NOT NULL `config_encrypted` column before it was ever set; local-user
  import checking for an existing account only within the *target*
  tenant when `control.users.email` is unique *instance-wide*, so
  importing a user whose email already existed under a *different*
  tenant hit that constraint as a raw, unhandled `IntegrityError`
  instead of this function's own "already exists, left unchanged"
  skip). All six are fixed; see the commit that added this paragraph
  for the specifics.
- **No HTTP-level tests at all** -- nothing in this suite drives a
  route through FastAPI's `TestClient`. A routing/template bug (a
  filter silently matching nothing, a redirect going to the wrong
  place) has to be caught by hand today.
- **Whole modules still with zero coverage**: `admin` (every screen
  and route, including the Config Bundle ones -- the integration tests
  above exercise `config_bundle.py`'s build/apply functions directly,
  not the admin router or templates in front of them), `portal`,
  `home`, `auth`'s LDAP/SAML flows, and most of `tickets.service` (the
  single biggest file in the codebase) beyond what the integration
  tests happen to touch in passing. The Documents Kanban board's own
  router (`GET /documents/kanban` and its two drag-and-drop endpoints)
  has the same gap -- the integration tests above exercise
  `service.retag`/`update_owner` directly, not the routes or template
  in front of them, same shape as the tickets/config-bundle gaps just
  above. `documents.service`'s webhook-refresh *orchestration*
  (`refresh_from_webhook`/`refresh_many_from_webhook`, as opposed to
  the pure helpers they call) is also untested.

None of that is a reason to avoid changing those areas -- it's a
reason to add a test alongside a change there rather than assuming one
already exists. `test_pure_functions.py`/`test_rules.py`/
`test_recurrence.py`/`test_platform_events_matching.py`/
`test_documents_pure.py` are good templates for a plain function; for
something that needs a DB, add a case to `test_integration.py` rather
than standing up a second integration-test file.

## How to append changes

### Add a field to an existing table

1. Add the column to the model in `tenant_models.py` (or
   `control_models.py`, rare) -- explicit `schema=` only for
   `control_models.py`, never for a tenant one (see that file's own
   docstring on why).
2. Add a migration under `migrations/tenant/versions/` (or `control/`)
   -- next sequential number, explicit `schema=` on every DDL op for a
   tenant migration (Alembic won't infer the tenant schema itself).
3. Wire it through wherever the record is created/edited: the relevant
   `service.py` function, the `router.py` form field, the template.
4. Update `docs/database-schema.md`'s entry for that table.
5. If it's user-facing, update `docs/user-guide.md`'s description of
   that screen.

### Add a tenant-wide setting

Most settings (a label, a flag, a page size -- not a per-record field)
don't need a new column at all:

1. Add a key to `TenantConfig.DEFAULTS` in `rain/core/tenant_config.py`
   with its default value and a comment explaining what it governs.
2. Read it with `get_tenant_config(db, "key")` (or `get_tenant_configs`
   for several at once) wherever it's needed; write it with
   `set_tenant_config`/`set_tenant_configs`.
3. If it's admin-editable, add a field to whichever Admin screen fits
   it best (often Branding's "Tenant defaults" card) and a form
   handler that saves it.
4. Document it in `docs/user-guide.md`'s Admin section.

### Add a whole new module

Follow an existing small module (`home` or `webhooks`) as the
template, not `tickets` (too much accumulated complexity to copy
blindly):

1. `modules/<name>/{__init__.py, router.py, service.py}` (add
   `schemas.py`/`nav.py` if needed).
2. If it needs a sidebar entry, register a `NavNode` in `nav.py`.
3. In `main.py`: import the `nav` submodule (if any) alongside the
   other `# noqa: F401` nav imports, then import and
   `app.include_router(...)` the router -- both steps, or the module
   doesn't exist in the running app.
4. Templates under `web/templates/<name>/`, extending `base.html`.
5. New tables (if any): models + a migration, per "Add a field" above.
6. Document the new module in this file's own module map, in
   `docs/database-schema.md` if it added tables, and in
   `docs/user-guide.md` if it's user-facing.

### Add a new admin screen

Same router+service+template shape as any module, but living in
`modules/admin/router.py` (it's one file for the whole Admin section,
not one per screen) and gated with `require_internal_admin` (Platform
Administration) or `require_admin` (Tenant Administration, reachable
by `client_admin` too) instead of the plain `require_login` most
other routes use.

### Keep the docs in sync

After a change that touches any of these, update the matching doc in
the same change, not as a follow-up:

| Changed | Update |
|---|---|
| A table/column | `docs/database-schema.md` |
| A module's responsibilities, a new module, a non-obvious design choice | `docs/architecture.md`, and this file's module map if it's structural |
| Anything a user/admin would notice | `docs/user-guide.md` |
| A capability worth a one-line mention | `README.md`'s bite-sized list |
