# RAIN

**RAIN is a self-hosted IT system of record built for environments that
can't (or won't) depend on a SaaS vendor** -- air-gapped networks,
classified or controlled-unclassified enclaves, and any organization that
needs its asset inventory, incident/vulnerability/change tickets, and
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
- Custom asset types with per-type custom fields (text, number, boolean,
  date, URL, email, select)
- CSV / JSON / Excel import and export, with reusable column/header/order
  profiles
- Tickets linked to an asset show on that asset's own page and PDF export

**Ticketing** -- the primary focus of the platform
- Three ticket types -- incident, vulnerability, and change -- sharing
  one record, one activity feed, and one export pipeline
- A built-in syslog listener turns any syslog-ng-fed event stream into a
  live event feed
- **Event Promotion Policies**: regex rules that auto-promote a matching
  syslog event into an incident or vulnerability ticket
- **Correlation Rules**: promote based on how many matching events land
  within a trailing time window, optionally grouped per host/program
- **Platform Response Rules**: react to new tickets by notifying Slack or
  email, calling a webhook, or attaching a document or asset -- every
  matching rule fires, and every firing is logged to the ticket
- **Webhooks**: centrally-configured outbound webhooks (Admin >
  Webhooks) -- one definition (URL, headers, payload, timeout, success
  codes) reused wherever a webhook call is needed, with an optional
  syslog alert if a call fails or times out
- **Live event triage**: bulk-promote, correlate, or discard selected
  events straight from the live feed, with a real-time status pill for
  the listener itself
- **Change tickets**: promoted from an existing incident/vulnerability or
  filed directly, with a required, tenant-defined approval flow and a
  scheduled start/end window shown on the ticket and the tenant calendar
- **Groups**: named sets of users an approval step can target as a whole
- Title, priority, assignee, and affected asset are all editable after
  creation, with every change logged to the ticket's activity feed
- Tenant-customizable ticket statuses instead of a fixed open/closed enum
- A unified, chronological activity feed per ticket -- comments, field
  changes, assignment/asset changes, approval decisions, and rule
  firings, newest- or oldest-first
- **Chronic flag** for recurring issues, shown in the list and on the
  ticket
- Quick-action menu and filter chips on every ticket list
- Branded PDF export of any ticket, including its full activity history
- Email/Slack notification channels, reusable across any number of rules

**Calendar**
- Per-tenant calendar with a visual month-grid editor
- Recurring-entry presets (quarterly, every 6 months, annually, one-time)
- Change tickets with a start/end window appear automatically alongside
  manual entries
- **Syslog bridge**: flag an entry to synthesize a syslog event on each
  occurrence, so the same rule engine that reacts to real syslog traffic
  can react to a recurring calendar entry too
- **Auto-update**: point an entry at a webhook-populated document, and
  each occurrence refreshes it the same way that document's own "Refresh
  from webhook" button would
- Standard iCalendar (.ics) export/import

**Document Repository**
- `DOC-xxxxxx` entries with description, file attachment, and links to
  any asset or ticket
- A document's contents can be populated by calling a configured
  webhook, with the new content diffed against what's stored and an
  optional syslog alert when it changes
- Branded PDF export, noting the source webhook and last-refresh date
  when a document is webhook-populated

**Platform**
- Schema-per-tenant multi-tenancy on a single Postgres instance
- Local email/password auth, plus an optional LDAP/Active Directory
  provider; OIDC/SAML provider slots are modeled, ready for a future
  release
- Role-based access control (`internal_admin` / `client`), with an Admin
  console for platform- and tenant-level configuration
- Runtime branding: instance name, accent color, logo, and font
- A resizable, searchable, collapsible tree navigation sidebar, with live
  count badges and an always-visible indicator of which tenant's data is
  on screen
- The user menu shows the current database schema build number
- Contextual help on every page, and pagination on every list screen

See [`docs/architecture.md`](docs/architecture.md) for the detailed
design, lessons from real deployment testing, and the current roadmap.

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
`SYSLOG_PORT` (default `5514`, TCP or UDP) -- Admin > Syslog Listener shows
the exact destination snippet, a real-time status pill, and lets you map
hosts/programs to tenants (or discard a noisy source outright).

## Stack

| Piece | Choice | Why |
|---|---|---|
| Frontend edge | Caddy (alpine) | Automatic HTTPS, reverse proxy, nothing else to configure |
| App | FastAPI + Jinja2, server-rendered | No Node/SPA build, no third-party JS framework to track for CVEs |
| DB | Postgres with pgvector | pgvector installed now, unused until a future search feature |
| Multi-tenancy | Schema-per-tenant | One Postgres instance, isolated per tenant |
| Auth | Local email/password + optional LDAP | OIDC/SAML planned |
| Ticketing bus | Built-in syslog listener (TCP+UDP) | syslog-ng pushes to it directly, no third-party syslog library |
| Document storage | Local volume behind a storage abstraction | Swappable for S3 later without touching callers |
| Exports | CSV, JSON, Excel, PDF, iCalendar | All pure-Python, no extra system dependencies in the image |

`caddy`/`app`/`worker` are multi-stage, Alpine-based builds; `db` uses
pgvector's official image. Only Caddy's ports (and the worker's syslog
port) are published to the host.

## Repository layout

```
docker-compose.yml, Caddyfile, db/Dockerfile   -- infra
backend/
  Dockerfile, pyproject.toml
  alembic.ini, migrations/{control,tenant}/    -- two independent migration chains
  src/rain/
    settings.py         -- the only place env vars are read
    db/                  -- models, engine/session, tenant provisioning
    core/                 -- security, RBAC, tenancy resolution, config store, nav registry
    modules/{setup,auth,admin,assets,tickets,calendar,documents,webhooks}/  -- one router+service per feature area
    web/                   -- Jinja2 templates, hand-written CSS/JS
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
app, migrations run automatically at startup, including catching up any
tenant schema that's behind head.

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
- OIDC/SAML auth providers (LDAP is done).
- Multiple independent LDAP directories (currently one directory syncs
  into exactly one target tenant, instance-wide).
