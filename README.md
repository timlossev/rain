# RAIN

**RAIN** (Response to Asynchronous Interactions in Networks) is a
self-hosted IT system of record built for environments that can't (or
won't) depend on a SaaS vendor -- air-gapped networks, classified or
controlled-unclassified enclaves, and any organization that needs its
asset inventory, incident/vulnerability/change tickets, and compliance
documentation to live entirely on infrastructure it controls.
One `docker compose up` stands up the whole stack -- reverse proxy with
automatic HTTPS, application, background worker, and database -- with no
external service to reach, no telemetry phoning home, and no license
server to check in with.

It's multi-tenant, configures itself at runtime through an in-app setup
wizard and Admin console (almost nothing lives in environment variables
or config files once it's running), and every image is a minimal,
Alpine-based build with no Node/SPA toolchain and no third-party
JS framework in the browser.

![RAIN screenshot](RAIN%20screenshot.png)

## Motivation

Compliance frameworks -- FedRAMP, ISO 27001, PCI-DSS, SOX, and their
international counterparts (Germany's BSI IT-Grundschutz, France's
SecNumCloud, Canada's ITSG-33, Singapore's MAS TRM, and others) -- don't
accept a policy document as evidence that a control is satisfied. They
require an artifact: a change ticket showing who approved what and when,
an incident record with a full timeline, a CMDB entry proving an asset
was tracked, an access request with a documented approval chain. A
structured system of record is the only mechanism that generates that
evidence continuously, at scale, in a form a third-party assessor can
sample and verify -- a policy that says "we review access" is not
evidence that any particular access was reviewed; a ticket is.

That's what RAIN is for. In a reference FedRAMP High authorization
package, 33 of 409 implemented controls -- concentrated in the
highest-scrutiny families (Configuration Management, Incident Response,
Access Control) -- have implementation statements that depend on exactly
this: ticketing, change approval workflows, and a configuration item
registry. That proportion (~8%) holds fairly steady at Moderate and Low
too, not just High, and a second tier of controls outside that 33 --
POA&M tracking chief among them -- can lean on the same ticket/document/
calendar primitives as indirect evidence. See
[`docs/itsm-controls-mapping.md`](docs/itsm-controls-mapping.md) for the
full control-by-control breakdown, the per-baseline estimates, and the
same mapping against ISO 27001, PCI-DSS, SOX, and a dozen national
frameworks across the EU, Canada, and Asia-Pacific.

Those tickets and incident records have to originate from somewhere,
which is why RAIN is deliberately "bring your own" for detection --
monitoring, SIEM, XDR, antivirus, whatever's already watching the
environment (Wazuh, Elastic, Splunk, CrowdStrike, Suricata, or anything
else). RAIN isn't trying to replace any of that or be integrated with
it one vendor API at a time; all it needs is an event, and just about
every monitoring or security product built in the last thirty years
already knows how to emit one over Syslog, natively or with minimal
forwarder config. That's why the event bus is a built-in Syslog
listener rather than a growing list of bespoke integrations: point
whatever's already generating alerts at RAIN, and Event Promotion
Policies turn that stream into the tickets and incident records the
frameworks above actually require -- without asking anyone to rip out a
detection stack that already works.

Not every one of those tools puts the same thing inside the syslog
message body, though -- some send plain text, some send CEF (Wazuh
included, among many others), some send JSON, some send loose
Splunk-style key=value pairs. RAIN's listener recognizes and parses
all four automatically, per event, with nothing to configure -- see
Ticketing below.

## Capabilities

**Asset Registry**
- Ships with no pre-defined asset types -- a server tracking physical
  attributes and configuration, a container tracking its build
  lifecycle, an access credential tracking expiration and clearance, a
  contact with associated contact methods, or anything else your
  organization tracks, is just a type plus custom fields (text, number,
  boolean, date, URL, email, select) you define yourself. No prescribed
  methodology -- RAIN isn't Agile or ITIL out of the box, on purpose, so
  the constructs and the workflow are yours to decide
- CSV / JSON / Excel import and export, with reusable column/header/order
  profiles
- Tickets linked to an asset show on that asset's own page and PDF export

**Ticketing** -- the primary focus of the platform
- Three ticket types -- incident, vulnerability, and change -- sharing
  one record, one activity feed, and one export pipeline
- Optional custom fields (same text/number/boolean/date/URL/email/select
  types as the Asset Registry's, tenant-wide across all three ticket
  types) -- a default tenant schema defines none, but any defined become
  capturable on the ticket form/detail page and importable/exportable
  right alongside the built-in columns
- CSV / JSON / Excel import (create-only -- incident/vulnerability; a
  change needs an approval flow attached by hand) and export, with
  reusable column/header/order profiles, mirroring the Asset Registry's
- A built-in syslog listener turns any syslog-ng-fed event stream into a
  live event feed -- auto-detects and parses CEF, JSON, and Splunk-style
  key=value message bodies alongside plain syslog text, no per-source
  configuration needed
- **Event Promotion Policies**: regex rules that auto-promote a matching
  syslog event into an incident, vulnerability, or change ticket -- one
  event per ticket ("single"), or repeats of the same thing folded into
  one already-open ticket instead of a fresh one each time (marked
  Problematic, "repetition"); an "ML anomaly" policy instead learns
  normal traffic per rule (optionally grouped per host/program), on a
  selectable `river.anomaly` algorithm (Half-Space Trees, Local Outlier
  Factor, or One-Class SVM, each with a plain-language explanation of
  what it's better at), and fires on a genuinely unusual event, running
  alongside the other two rather than competing with them for the same
  event
- **Root cause assistance**: an "Analyze root cause" button on any
  ticket (or automatically at closure, opt-in per tenant) posts a
  comment summarizing a repeat-occurrence pattern and similar past
  closed tickets -- honest statistical/historical signals, not causal
  reasoning
- **Platform Response Rules**: react to new tickets by notifying Slack or
  email, calling a webhook, attaching a document or asset, marking the
  ticket problematic, or adding a watcher (a system user or a bare
  email) -- every matching rule fires, and every firing is logged to
  the ticket
- **Watchers**: opt in ("Watch" on the ticket detail page) or added
  automatically (reporter, assignee, or a Platform Response Rule) to get
  emailed on a ticket's new comments and status changes
- **Escalate**: a one-click button on every ticket that calls a tenant's
  configured escalation webhook on demand, logged to the ticket's
  activity feed
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
- **Problematic flag** for recurring issues, shown in the list and on the
  ticket
- Quick-action menu and filter chips on every ticket list
- Branded PDF export of any ticket, including its full activity history
- Email/Slack notification channels, reusable across any number of rules

**Service Catalog**
- Tenant-defined, requestable forms (Admin > Service Catalog, reachable
  from Records Authority or the client portal below) -- each one up to
  10 questions (text, number, date, URL, email, yes/no, or a dropdown)
  that produce an incident, vulnerability, or change ticket on
  submission, its description the answers serialized as JSON or
  `key=value` lines
- A change service is optionally routed through an approval flow, the
  same machinery Change tickets use directly
- A question's value can come from an existing Document instead of
  free-form entry -- used as-is, or narrowed with a regex or a JSONPath,
  with a live Preview while designing the form

**Client Portal**
- A public per-tenant page (`/portal/<slug>`), no account needed --
  "Request Something" (the Service Catalog above) and "Report Something"
  (file an incident) are open to every visitor
- Sign in for a search bar plus "Pending Actions" (tickets awaiting your
  approval) and "Document Archive" tabs, and an Escalate button next to
  your own reported tickets
- "Today's events", pulled from the tenant calendar, shown to every
  visitor regardless of sign-in status
- Two settings gate the whole page (Admin > Branding): require sign-in
  to file/request anything at all, and whether the page carries this
  instance's own branding or stays neutral for sharing outside the
  organization
- An optional full-page background image (Admin > Branding), shown for
  any tenant with that branding setting on; unset by default, same
  plain background as ever
- **Shareable documents**: a document flagged "Shareable in the client
  portal" appears in a tab reachable by every visitor, including one
  with no account at all, even on a tenant that requires sign-in for
  the rest of the portal; the tab (renamable, e.g. "Trust Center", on
  Admin > Branding) only shows up once a shareable document exists

**Calendar**
- Per-tenant calendar with a visual month-grid editor
- Recurring-entry presets (daily, weekly, monthly, quarterly, every 6
  months, annually, one-time)
- Change tickets with a start/end window appear automatically alongside
  manual entries
- **Syslog bridge**: flag an entry to synthesize a syslog event on each
  occurrence, so the same rule engine that reacts to real syslog traffic
  can react to a recurring calendar entry too
- **Related document**: tie an entry to a document (e.g. a quarterly
  revision reminder), manageable either here or from that document's
  own Calendar tab -- optionally also **auto-refreshing** it from its
  configured webhook on each occurrence, the same way that document's
  own "Refresh from webhook" button would
- Standard iCalendar (.ics) export/import

**Document Repository**
- `DOC-xxxxxx` entries with description, optional freeform tags, file
  attachment, and links to any asset or ticket
- Storage is local disk by default, or an S3 (or S3-compatible -- MinIO,
  etc.) bucket if `S3_BUCKET` is set in `.env` -- no code changes, and no
  local uploads volume to persist once every document lives in the
  bucket instead
- A document's contents can be populated by calling a configured
  webhook, with the new content diffed against what's stored and an
  optional syslog alert when it changes
- A document's own Calendar tab: recurring or one-off reminders tied to
  it (e.g. "due for revision every quarter"), independent of the
  webhook auto-update above -- plain reminders unless one also opts
  into auto-refreshing that document on the same schedule
- Branded PDF export, noting the source webhook and last-refresh date
  when a document is webhook-populated

**Search**
- A global search bar (every page) for keyword search across ticket and
  document titles/descriptions/numbers (documents' tags included),
  Postgres full-text ranked, with match highlighting
- Typing a ticket, document, or asset number (`INC-000001`, `DOC-000004`,
  `CI-000001`) jumps straight to that record instead of a results page
- Ticket and document detail pages live at that same human-readable
  number (`/tickets/INC-000001`, `/documents/DOC-000004`)

**Platform**
- Schema-per-tenant multi-tenancy on a single Postgres instance
- Local email/password auth, plus optional LDAP/Active Directory and
  SAML 2.0 SSO providers -- a SAML sign-in is JIT-provisioned (or
  matched by email) with its role re-derived from a configurable
  attribute on every login
- Role-based access control: `internal_admin` (platform-wide), `client`
  (one tenant, no admin functions), and `client_admin` (one tenant, full
  admin rights over that tenant's own settings -- rules, flows, groups,
  channels, webhooks -- but not platform-wide ones). The Admin console
  itself splits the same way, into Platform Administration and Tenant
  Administration
- Runtime branding: instance name, accent color, logo, and font
- A resizable, searchable, collapsible tree navigation sidebar, with live
  count badges and an always-visible indicator of which tenant's data is
  on screen
- The user menu shows the current database schema build number
- Contextual help on every page, and pagination on every list screen
- A generated API spec (Swagger UI, grouped by area) at `/docs`, gated
  behind `internal_admin` like every other platform-wide setting --
  reference for the same server-rendered routes the UI itself calls,
  not a separate integration API (use Webhooks and Platform Response
  Rules for that)

See [`docs/user-guide.md`](docs/user-guide.md) for a task-oriented guide
to using RAIN day to day, [`docs/architecture.md`](docs/architecture.md)
for the detailed design, lessons from real deployment testing, and the
current roadmap, and [`docs/itsm-controls-mapping.md`](docs/itsm-controls-mapping.md)
for the compliance-control analysis behind why this project exists in
the first place (see Motivation above).

## Quickstart

Requires Docker and Docker Compose. Nothing else.

```sh
python bootstrap.py      # or bootstrap.ps1 / bootstrap.sh -- generates .env once
docker compose up --build
```

`bootstrap` generates strong random secrets either way, then asks a
handful of deployment questions -- built-in vs external Postgres (with
a live connection test, and, for an external one, whether it supports
the pgvector extension), local disk vs S3 document storage, a separate
worker container vs merging it into `app`, and Caddy vs an existing
reverse proxy/load balancer in front of RAIN -- defaulting to the setup
above if you just press Enter, or skipping the questions entirely (same
defaults) when run non-interactively, e.g. in CI. It only ever runs
once; a `.env` that already exists is left untouched.

Then visit `https://localhost` (Caddy issues a certificate automatically --
from its internal CA for `localhost`, or via public ACME if you set
`RAIN_DOMAIN` in `.env` to a real, publicly-resolvable domain first).
The first visit runs a setup wizard: instance name, accent color, an
optional logo, your first tenant, and the first internal admin account.
Everything else -- SMTP, Slack, additional tenants and users, asset types,
custom fields, syslog source routing, documents -- is configured afterwards
from the Admin console, stored in Postgres.

To feed the ticketing side, point a syslog-ng destination at this host on
`SYSLOG_PORT` (default `5514`, TCP or UDP) -- see
[`docs/architecture.md`](docs/architecture.md#ticketing-milestone-2-full-scope)
for the destination snippet. Admin > Syslog Listener shows a real-time
status pill, lets you map hosts/programs to tenants (or discard a noisy
source outright), and sets how long an event that never got promoted
into a ticket sticks around before being discarded (12 hours by default).

A few more `.env` settings support deploying behind existing
infrastructure instead of the full default stack: `POSTGRES_URL` points
RAIN at an external/managed Postgres instead of running its own `db`
container; `APP_PORT` changes what the app listens on; `WEB_FRONTEND=false`
skips the Caddy container for deployments that already terminate TLS in
front of RAIN (e.g. an AWS ALB) -- also drop `web-frontend` from
`COMPOSE_PROFILES` when you do, since that (not `WEB_FRONTEND`) is what
Compose actually reads to decide whether to start it; `S3_BUCKET` (+
`S3_REGION`/`S3_ENDPOINT_URL`/`S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY`)
points document storage at an S3 (or S3-compatible) bucket instead of the
local uploads volume; `ENABLE_PGVECTOR=false` skips creating the Postgres
`vector` extension (and the reserved, currently-unused embedding columns
that depend on it) for an external Postgres that can't create it -- a
managed-database role without `CREATE EXTENSION` privilege
(`asyncpg.exceptions.InsufficientPrivilegeError`), or the extension not
being offered at all (standard RDS in AWS GovCloud). `bootstrap` asks
about all of this interactively too. See the comments in `.env.example`.

Combine all of those with `EMBED_WORKER=true` (folds the `worker`
container's own duties -- syslog listener, rule engine, notifications,
calendar sweep, LDAP sync -- into the `app` container instead of running
them separately) for minimal mode: one container, no local Postgres,
no local storage volume, no Caddy.

```sh
docker compose -f docker-compose.yml -f docker-compose.minimal.yml up --build
```

For a remote/managed Postgres (RDS or similar), still no Compose, but
this repo checked out (for `backend/` to build from) -- `bootstrap`'s
questions above already cover single-container deployments too (say no
to the built-in Postgres container, yes to merging the worker in, and
answer the pgvector/Caddy questions honestly for your Postgres/network),
and it writes everything -- `POSTGRES_URL`, `APP_SECRET_KEY`,
`EMBED_WORKER=true`, `ENABLE_PGVECTOR`, `S3_*`, all of it -- into one
`.env`. Pass that straight to `docker run` with `--env-file` instead of
re-typing every setting as a separate `-e` flag; `bootstrap` prints the
exact command for you once it detects that's what you configured
(`EMBED_WORKER=true` + `WEB_FRONTEND=false`):

```sh
docker build -t rain-app ./backend
docker run -d --name rain --env-file .env -p 8000:8000 -p 5514:5514/tcp -p 5514:5514/udp rain-app
```

Serves plain HTTP on 8000 (no Caddy in this shape, so no automatic
HTTPS -- terminate TLS in front of it yourself if you need it) and
listens for syslog on 5514, same as `docker-compose.minimal.yml`'s
overlay. `RAIN_DOMAIN` is unused in this shape -- it's Caddy-only, and
there's no Caddy here -- so leave it as-is; nothing reads it. Stop any
other RAIN instance using ports 8000/5514 first (this repo's own
`docker compose` stack included) -- Docker fails to start a second
container on either with "port is already allocated" otherwise, it's
not specific to this deployment shape.

`ENABLE_PGVECTOR=false` is what makes this work at all against a
Postgres role that can't create extensions (typical for a minimum-
privilege application role -- `asyncpg.exceptions.
InsufficientPrivilegeError` is the error otherwise) or doesn't offer
`vector` in the first place (standard RDS in AWS GovCloud) -- confirmed
live against both a permission-denied and a does-not-exist Postgres,
including this exact `--env-file` shape end to end: migrations
complete, and nothing else in the app depends on the column it skips.

Skipping `bootstrap`/`.env` entirely and passing everything via `-e`
flags by hand still works -- `DATABASE_URL` (not `POSTGRES_URL`, which
only `.env`/Compose paths use) is what the app reads directly in that
case, e.g. `-e DATABASE_URL="postgresql://user:password@your-rds-endpoint:5432/rain"`.
RDS Postgres accepts a plain `postgresql://` DSN as-is unless you've
turned on `rds.force_ssl`, in which case add `?ssl=require` (asyncpg's
own query param, not the `sslmode=` one `psql`/libpq use).

See `docker-compose.minimal.yml`'s own comments for the exact `.env`
values this needs.

## Stack

| Piece | Choice | Why |
|---|---|---|
| Frontend edge | Caddy (alpine) | Automatic HTTPS, reverse proxy, nothing else to configure |
| App | FastAPI + Jinja2, server-rendered | No Node/SPA build, no third-party JS framework to track for CVEs |
| DB | Postgres, optionally with pgvector | Full-text search live now (tsvector/GIN); pgvector reserved for semantic search once an embedding source exists -- `ENABLE_PGVECTOR=false` skips it for a Postgres that can't create it |
| Multi-tenancy | Schema-per-tenant | One Postgres instance, isolated per tenant |
| Auth | Local email/password + optional LDAP + SAML 2.0 | `python3-saml` for SAML (XML signature verification, not hand-rolled) |
| Ticketing bus | Built-in syslog listener (TCP+UDP) | syslog-ng pushes to it directly, no third-party syslog library; foldable into the app container itself (`EMBED_WORKER=true`) for a single-container deployment |
| Document storage | Local volume, or S3/S3-compatible (`S3_BUCKET`) | Swappable behind one small abstraction, no caller touches either directly |
| Exports | CSV, JSON, Excel, PDF, iCalendar | All pure-Python, no extra system dependencies in the image |

`caddy`/`app`/`worker` are multi-stage, Alpine-based builds; `db` uses
pgvector's official image. Only Caddy's ports (and the worker's syslog
port) are published to the host.

## Repository layout

```
docker-compose.yml, docker-compose.minimal.yml, Caddyfile, db/Dockerfile   -- infra
charts/rain/                                    -- Helm chart, same deployment shapes as the two compose files
backend/
  Dockerfile, pyproject.toml
  alembic.ini, migrations/{control,tenant}/    -- two independent migration chains
  src/rain/
    settings.py         -- the only place env vars are read
    db/                  -- models, engine/session, tenant provisioning
    core/                 -- security, RBAC, tenancy resolution, config store, nav registry
    modules/{setup,auth,admin,assets,tickets,catalog,calendar,documents,portal,webhooks,search}/  -- one router+service per feature area
    web/                   -- Jinja2 templates, hand-written CSS/JS
  tests/
```

For Kubernetes instead of Compose, see [`charts/rain/README.md`](charts/rain/README.md) -- same deployment shapes (default two-workload, or a minimal single-workload mode), one Helm chart.

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

Contact: [inquiries@curated.systems](mailto:inquiries@curated.systems)

## Roadmap

Per [`docs/architecture.md`](docs/architecture.md#roadmap):

- Semantic/vector search (pgvector is enabled and each searchable table
  already carries a reserved `embedding` column; keyword search is live
  today -- this needs an embedding source, local or API-based, to
  actually populate and query those columns from).
- Multiple independent LDAP or SAML sources (currently one of each,
  syncing/signing into exactly one target tenant, instance-wide).
