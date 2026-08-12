# RAIN

**RAIN is a self-hosted IT system of record built for environments that
can't (or won't) depend on a SaaS vendor** -- air-gapped networks,
classified or controlled-unclassified enclaves, and any organization that
needs its asset inventory, incident/vulnerability tickets, and
compliance documentation to live entirely on infrastructure it controls.
One `docker compose up` stands up the whole stack -- reverse proxy with
automatic HTTPS, application, background worker, and database -- with no
external service to reach, no telemetry phoning home, and no license
server to check in with.

It's multi-tenant, configures itself at runtime through an in-app setup
wizard and Admin console (almost nothing lives in environment variables
or config files once it's running), and every image is a minimal,
Alpine-based build with no Node/SPA toolchain and no third-party
JS framework in the browser.

## Capabilities

**Asset Registry**
- Custom asset types and per-type custom fields (text, number, boolean,
  date, URL, email, select)
- CSV / JSON / Excel (.xlsx) import and export, with a saved,
  reusable column/header/order profile
- AWS/Azure cloud-sync connection scaffolding (discovery providers ready
  for a future release)

**Ticketing** -- the primary focus of the platform
- A hand-written syslog listener (TCP + UDP, no third-party library)
  turns any syslog-ng-fed event stream into a live event feed
- **Event Policies**: regex rules that auto-promote a matching syslog
  event into an `INC-xxxxxx` (incident) or `VULN-xxxxxx` (vulnerability)
  ticket, first match wins
- **Platform Events**: a second, independent reaction layer -- rules
  that match on ticket creation (title/description regex) and fire one
  or more actions: notify Slack, notify email, call a webhook with a
  custom JSON payload, attach a document, or attach an asset. Every
  active matching rule fires, and every firing is logged to the ticket's
  activity feed
- **Tenant-customizable ticket statuses** -- define your own workflow
  (labels, colors, which statuses count as "closed") instead of a fixed
  open/closed enum
- A merged, chronological activity feed per ticket: comments and status
  changes, with resolved commenter names, not raw user IDs
- Branded PDF export of any ticket, including its full activity history
- Email/Slack notification channels, configured once and reused by any
  number of Platform Event rules

**Calendar**
- Per-tenant calendar with a server-rendered month-grid visual editor
  (no client-side calendar library)
- Recurring-entry presets: quarterly, every 6 months, annually, or a
  one-time entry, with an optional end date
- **Syslog bridge**: flag an entry to synthesize a syslog event on each
  due occurrence, so the same Event Policy / Platform Event rule engine
  that reacts to real syslog traffic can also react to a recurring
  calendar entry (e.g. auto-file a ticket for a quarterly access review)
- Standard iCalendar (.ics) export/import, interoperable with Outlook,
  Google Calendar, and Apple Calendar
- A forward-looking, already-round-tripping hook for attaching a
  structured "policy" to a recurring entry (e.g. "update document X
  quarterly") -- carried through export/import today, acted on in a
  future release

**Document Repository**
- `DOC-xxxxxx` entries with description, file attachment, and
  polymorphic links to any asset or ticket
- Branded PDF export

**Platform**
- Schema-per-tenant multi-tenancy on a single Postgres instance
- Local email/password auth (Argon2, DB-backed sessions) with
  `OIDC/SAML/LDAP` provider slots already modeled, ready to enable in a
  future release
- Role-based access control (`internal_admin` / `client`), with an
  Admin console for platform- and tenant-level configuration
- Runtime branding: instance name, accent color, logo upload, and a
  curated, dependency-free font picker -- no CDN font download
- A resizable, searchable, collapsible tree navigation sidebar
- Pagination on every list screen in the app

See [`docs/architecture.md`](docs/architecture.md) for the detailed
design, every hard-won lesson from real deployment testing, and the
current roadmap.

## Quickstart

Requires Docker and Docker Compose. Nothing else.

```sh
python bootstrap.py      # or bootstrap.ps1 / bootstrap.sh -- generates .env once
docker compose up --build
```

Then visit `https://localhost` (Caddy issues a certificate automatically --
from its internal CA for `localhost`, or via public ACME if you set
`RAIN_DOMAIN` in `.env` to a real, publicly-resolvable domain first).
The first visit runs a setup wizard: instance name, accent color, an
optional logo, your first tenant, and the first internal admin account.
Everything else -- SMTP, Slack, additional tenants and users, asset types,
custom fields, syslog source routing, documents -- is configured afterwards
from the Admin console, stored in Postgres.

To feed the ticketing side, point a syslog-ng destination at this host on
`SYSLOG_PORT` (default `5514`, TCP or UDP) -- Admin > Syslog Sources shows
the exact destination snippet and lets you map hosts/programs to tenants.

## Stack

| Piece | Choice | Why |
|---|---|---|
| Frontend edge | Caddy (alpine) | Automatic HTTPS, reverse proxy, nothing else to configure |
| App | FastAPI + Jinja2, server-rendered | No Node/SPA build; the entire client-side footprint is one hand-written CSS file and a couple of small vanilla-JS files -- no htmx/Alpine/Tailwind/React dependency to track for CVEs |
| DB | `pgvector/pgvector:pg17-trixie` (official image, pgvector pre-installed) | pgvector installed now, unused until the future LLM search hook; official image avoids maintaining our own pgvector build |
| Multi-tenancy | Schema-per-tenant | One Postgres instance, `control` schema for platform data, `tenant_<slug>` per tenant |
| Auth | Local email/password (Argon2, DB-backed sessions) | `control.auth_providers` already has disabled OIDC/SAML/LDAP rows, ready for a future release |
| Ticketing bus | Hand-written syslog listener (TCP+UDP) in `worker` | No third-party syslog library; syslog-ng pushes to it as a `network()` destination |
| Document storage | Local volume behind a `StorageBackend` abstraction | Swappable for S3 later without touching callers; served only through an authenticated download route, never the static file mount |
| Exports | CSV, JSON, Excel (`openpyxl`), PDF (`xhtml2pdf`), iCalendar | All pure-Python, no headless browser or system library required in the image |

`caddy`/`app`/`worker` are multi-stage, Alpine-based builds; `db` uses
pgvector's official image (Debian-based -- pgvector doesn't publish an
Alpine variant, and compiling it ourselves wasn't worth the maintenance
burden, see `db/Dockerfile`). Only Caddy's ports (and the worker's syslog
port) are published to the host.

## Repository layout

```
docker-compose.yml, Caddyfile, db/Dockerfile   -- infra
backend/
  Dockerfile, pyproject.toml
  alembic.ini, migrations/{control,tenant}/    -- two independent migration chains
  src/rain/
    settings.py        -- the only place env vars are read
    db/                 -- models, engine/session, tenant provisioning
    core/                -- security, RBAC, tenancy resolution, config store, nav registry
    modules/{setup,auth,admin,assets,tickets,calendar,documents}/  -- one router+service per feature area
    web/                  -- Jinja2 templates, hand-written CSS/JS
  tests/
```

## Development

```sh
cd backend
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
pytest                                            # pure-function tests, no DB needed
TEST_DATABASE_URL=postgresql+asyncpg://rain:rain@localhost:5432/rain_test pytest tests/test_integration.py
```

Alembic runs from `backend/` against whichever section you need, e.g.
`alembic -n control upgrade head` for local exploration -- in the running
app, migrations are driven programmatically (`rain.db.migrate`) and run
automatically at startup, including catching up any tenant schema that's
behind head.

Set `DEBUG=true` in `.env` to get full tracebacks inline in 500 responses
instead of a bare "Internal Server Error" (requires recreating the `app`
container to pick up). Never set it true anywhere but a local checkout --
see [`docs/architecture.md`](docs/architecture.md#lessons-from-the-first-real-docker-run)
for why it exists.

## Support

Commercial support plans, deployment assistance, and patch/update
cadences aligned with U.S. Government timeliness expectations for
security-relevant fixes are available. Reach out for details on support
tiers, SLAs, and delivery for air-gapped and controlled environments.

> Maintainer's note: the paragraph above is boilerplate the repository
> owner asked to have here -- tailor it to your actual support offering,
> SLA numbers, and any compliance posture you can substantiate (e.g. a
> specific framework or ATO) before publishing it somewhere a government
> customer will read it as a commitment.

## Roadmap

Per [`docs/architecture.md`](docs/architecture.md#roadmap):

- pgvector-backed keyword/vector search hook (pgvector is already
  installed, unused).
- Real AWS/Azure asset discovery (`SyncProvider.discover_assets()` is
  currently a stub).
- OIDC/SAML/LDAP auth providers (`control.auth_providers` rows already
  exist, disabled).
- Acting on `CalendarEntry.policy_ref` (currently an inert, round-tripping
  hook for a future "recurring policy" concept, e.g. "update document X
  quarterly").
