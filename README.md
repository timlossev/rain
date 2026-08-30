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

### At a glance

- Landing page shows a welcome message, or a flagged document
- Incident, vulnerability, and change tickets, one shared record shape
- Built-in syslog listener, auto-parses plain text, CEF, JSON, key=value
- Event Promotion Policies turn matching syslog events into tickets
- Optional ML anomaly detection, no manual tuning required
- Root cause assistance surfaces repeat patterns and similar past tickets
- Platform Response Rules react to ticket lifecycle events automatically
- No-code asset types and custom fields, define your own
- Document repository with tags, webhook auto-population, and PDF export
- Per-tenant calendar with recurring entries and a syslog bridge
- Tenant-defined Service Catalog forms that produce tickets on submission
- Public client portal for external incident reporting and requests
- Shareable documents ("Trust Center") for public-facing compliance proof
- Global full-text search across tickets, documents, and assets
- CSV/JSON/Excel import and export wherever records live
- Branded PDF export for tickets and documents
- Local auth plus optional LDAP/Active Directory and SAML 2.0 SSO
- Role-based access control across platform and per-tenant admin tiers
- Runtime branding: instance name, accent color, logo, font
- Schema-per-tenant multi-tenancy on one Postgres instance
- Self-hosted, air-gapped-capable, no telemetry, no license server

The rest of this section follows the sidebar, in order: Home, Records
Authority, Calendar, Assets, Documents, then Admin (where most rules,
integrations, and tenant-wide settings actually live -- a lot of what
reacts to tickets is configured there, not under Records Authority
itself). Client Portal and Search sit outside the sidebar entirely, so
they're covered last.

### Home

The landing page (also what signing in lands you on). A plain "Welcome
to `<instance name>`" by default -- or, if any document is flagged
"Show on landing page" (from that document's own Properties tab, see
Documents below), that document's own content instead, rendered as
Markdown (or plain text for a non-Markdown text file) rather than
linking out to it. More than one flagged document all show, stacked in
title order.

### Records Authority

Tickets, and everything about working one.

- Three ticket types -- incident, vulnerability, and change -- sharing
  one record, one activity feed, and one export pipeline
- **Events**: a live feed off the built-in syslog listener (auto-detects
  and parses CEF, JSON, and Splunk-style key=value message bodies
  alongside plain syslog text, no per-source configuration needed), with
  bulk-promote/correlate/discard straight from the feed and a real-time
  listener status pill
- Optional custom fields (text, number, boolean, date, URL, email,
  select), tenant-wide across all three ticket types -- a default tenant
  schema defines none, but any defined become capturable on the ticket
  form/detail page and importable/exportable right alongside the
  built-in columns
- CSV / JSON / Excel import (create-only -- incident/vulnerability; a
  change needs an approval flow attached by hand) and export, with
  reusable column/header/order profiles
- **Root cause assistance**: "Analyze root cause" (on the ticket, or its
  row menu) opens a preview -- a repeat-occurrence pattern and similar
  past closed tickets, honest statistical/historical signals, not causal
  reasoning -- with the choice to post it as a comment, copy it, or just
  close it; optionally also automatic, once, at closure (opt-in, under
  Admin)
- **Escalate**: a one-click button that calls the tenant's configured
  escalation webhook (Admin), logged to the ticket's activity feed
- **Watchers**: opt in ("Watch" on the ticket) or added automatically
  (reporter, assignee, or a Platform Response Rule) to get emailed on a
  ticket's new comments and status changes
- **Problematic flag** for recurring issues, toggleable inline, shown in
  the list and on the ticket
- **Change tickets**: promoted from an existing incident/vulnerability or
  filed directly, with a required, tenant-defined approval flow (Admin)
  and a scheduled start/end window shown on the ticket and the tenant
  calendar
- Tenant-customizable statuses (Admin) instead of a fixed open/closed
  enum; title, priority, assignee, and affected asset are all editable
  after creation, every change logged to the activity feed
- A unified, chronological activity feed per ticket -- comments, field
  changes, assignment/asset changes, approval decisions, and rule
  firings, newest- or oldest-first
- Quick-action row menu and filter chips on the list -- correlates 1:1
  with the ticket detail page's own top-right button row, so nothing
  there needs a full page visit to reach
- Branded PDF export of any ticket, including its full activity history
- **Service Catalog**: requestable, tenant-defined forms (defined under
  Admin, reachable here or from the client portal) produce a ticket on
  submission -- each one up to 10 questions (text, number, date, URL,
  email, yes/no, or a dropdown), a change service optionally routed
  through an approval flow, and a question's value can come from an
  existing Document instead of free-form entry

### Calendar

- Per-tenant calendar with a visual month-grid editor
- Recurring-entry presets (daily, weekly, monthly, quarterly, every 6
  months, annually, one-time)
- Change tickets with a start/end window appear automatically alongside
  manual entries
- **Syslog bridge**: flag an entry to synthesize a syslog event on each
  occurrence, so the same rule engine that reacts to real syslog traffic
  can react to a recurring calendar entry too
- **Related document**: tie an entry to a document (e.g. a quarterly
  revision reminder), manageable either here or from that document's own
  Calendar tab -- optionally also **auto-refreshing** it from its
  configured webhook on each occurrence, the same way that document's
  own "Refresh from webhook" button would
- Standard iCalendar (.ics) export/import

### Assets

- Ships with no pre-defined asset types -- a server tracking physical
  attributes and configuration, a container tracking its build
  lifecycle, an access credential tracking expiration and clearance, a
  contact with associated contact methods, or anything else your
  organization tracks, is just a type plus custom fields (text, number,
  boolean, date, URL, email, select) you define yourself (Admin). No
  prescribed methodology -- RAIN isn't Agile or ITIL out of the box, on
  purpose, so the constructs and the workflow are yours to decide
- Browse all assets, or by type, with tenant-wide custom fields
- CSV / JSON / Excel import and export, with reusable column/header/order
  profiles
- Tickets linked to an asset show on that asset's own page and PDF export

### Documents

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
  it (e.g. "due for revision every quarter"), independent of the webhook
  auto-update above -- plain reminders unless one also opts into
  auto-refreshing that document on the same schedule
- **Shareable documents**: a checkbox on the document's own page exposes
  it through a tab in the client portal, reachable by every visitor
  including one with no account at all, even on a tenant that requires
  sign-in for the rest of the portal; the tab (renamable, e.g. "Trust
  Center", under Admin) only appears once a shareable document exists
- **Landing page content**: a separate checkbox shows a document's own
  content (rendered Markdown, or plain text) on Home instead of just
  linking to it -- see Home above
- Branded PDF export, noting the source webhook and last-refresh date
  when a document is webhook-populated

### Admin

Split into two tiers -- Platform Administration (instance-wide,
`internal_admin` only) and Tenant Administration (the active tenant's
own settings, reachable by `client_admin` too) -- which is also where
most of what *reacts to* a ticket, asset, or document actually lives,
even though its effect shows up under Records Authority/Assets/
Documents above.

**Platform Administration**
- **Branding**: instance name, accent color, logo, font, and the client
  portal's optional full-page background image
- **Tenants**: create new tenants, switch which one is active
- **Auth Providers**: LDAP/Active Directory sync, and SAML 2.0 SSO
  (JIT-provisioned or matched by email, role re-derived from a
  configurable attribute on every login)
- **SMTP Relay**: outbound email settings, shared by every notification
  channel and system email
- **Syslog Listener**: real-time listener status, host/program-to-tenant
  routing (or discard a noisy source outright), and how long an
  un-promoted event sticks around before being discarded
- **Users**: internal admin and client accounts
- **API Documentation**: a generated Swagger UI reference for the same
  server-rendered routes the UI itself calls (see Search below for why
  this isn't a separate integration API)

**Tenant Administration**
- **Groups**: named sets of users an approval step can target as a whole
- **Ticket Statuses**: the tenant's own status set, replacing a fixed
  open/closed enum
- **Notification Channels**: reusable Slack/email/webhook destinations,
  shared across any number of rules
- **Approval Flows**: ordered steps (a group or an individual), attached
  to change tickets and change-producing Service Catalog items
- **Event Promotion Policies**: regex rules that turn a matching syslog
  event into an incident, vulnerability, or change ticket -- one event
  per ticket ("single"), or repeats folded into one already-open ticket
  instead of a fresh one each time (marked Problematic, "repetition" --
  on by default, also flags statistically unusual occurrences among
  those repeats as a comment, using a selectable `river.anomaly`
  algorithm with no further tuning needed); a standalone "ML anomaly"
  policy instead learns normal traffic per rule (optionally grouped per
  host/program) and fires its own ticket on a genuinely unusual event,
  useful for watching a broad/unfiltered stream that isn't otherwise
  being repetition-tracked, and shows its own training progress -- "No
  events yet", "115/250 training", "Live", or a mixed summary for a
  grouped policy -- both on the policy list and, broken down per group,
  on its own edit page. A policy producing a change ticket can name
  which approval flow to attach, and defaults that ticket's
  implementation window to starting at creation with a 24h turnaround
- **Platform Response Rules**: react to a ticket being created, closed,
  or (changes) fully approved by notifying Slack or email, calling a
  webhook, attaching a document or asset, marking the ticket problematic,
  or adding a watcher -- every matching rule fires, and every firing is
  logged to the ticket
- **Webhooks**: one definition (URL, headers, payload, timeout, success
  codes) reused wherever a webhook call is needed -- rules, document
  auto-population -- with an optional syslog alert if a call fails or
  times out
- **Asset Types**: define the types and custom fields Assets above
  tracks
- **Service Catalog**: design the requestable forms Records Authority
  and the client portal surface, with a live Preview while building one
- **Import Ticket Field Pack**: bulk-define ticket custom fields from a
  spreadsheet, with type-guessing from sample data
- **Incident Portal**: the client portal's own per-tenant settings (see
  Client Portal below)

### Client Portal

A public per-tenant page (`/portal/<slug>`), outside the sidebar
entirely -- no account needed for the basics.

- "Request Something" (the Service Catalog above) and "Report Something"
  (file an incident) are open to every visitor
- Sign in for a search bar plus "Pending Actions" (tickets awaiting your
  approval) and "Document Archive" tabs, and an Escalate button next to
  your own reported tickets
- "Today's events", pulled from the tenant calendar, shown to every
  visitor regardless of sign-in status
- Shareable documents (see Documents above) in their own tab, reachable
  even on a tenant that otherwise requires sign-in for the rest of the
  page
- Two settings gate the whole page (Admin > Branding): require sign-in
  to file/request anything at all, and whether the page carries this
  instance's own branding or stays neutral for sharing outside the
  organization

### Search

Also outside the sidebar -- a bar on every signed-in page instead.

- Keyword search across ticket and document titles/descriptions/numbers
  (documents' tags included), Postgres full-text ranked, with match
  highlighting
- Typing a ticket, document, or asset number (`INC-000001`, `DOC-000004`,
  `CI-000001`) jumps straight to that record instead of a results page
- Ticket and document detail pages live at that same human-readable
  number (`/tickets/INC-000001`, `/documents/DOC-000004`)

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
    modules/{setup,auth,admin,assets,tickets,catalog,calendar,documents,home,portal,webhooks,search}/  -- one router+service per feature area
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
