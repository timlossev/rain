# RAIN

**RAIN** (Response to Asynchronous Interactions in Networks) is a
self-hosted IT system of record built for environments that can't (or
won't) depend on a SaaS vendor -- air-gapped networks, classified or
controlled-unclassified enclaves, and any organization that needs its
asset inventory, incident/vulnerability/change tickets, and compliance
documentation to live entirely on infrastructure it controls. One
`docker compose up` stands up the whole stack with no external service
to reach, no telemetry phoning home, and no license server to check in
with. It's multi-tenant, configures itself at runtime through an in-app
setup wizard and Admin console, and every image is a minimal,
Alpine-based build with no Node/SPA toolchain in the browser.

![RAIN screenshot](RAIN%20screenshot.png)

## Motivation

Compliance frameworks -- FedRAMP, ISO 27001, PCI-DSS, SOX, and their
international counterparts -- don't accept a policy document as evidence
that a control is satisfied. They require an artifact: a change ticket
showing who approved what and when, an incident record with a full
timeline, a CMDB entry proving an asset was tracked. A structured
system of record is the only mechanism that generates that evidence
continuously, at a scale a third-party assessor can sample and verify.
In a reference FedRAMP High authorization package, 33 of 409
implemented controls depend on exactly this -- see
[`docs/itsm-controls-mapping.md`](docs/itsm-controls-mapping.md) for
the full control-by-control breakdown across a dozen frameworks
worldwide.

Those tickets have to originate from somewhere, which is why RAIN is
deliberately "bring your own" for detection -- monitoring, SIEM, XDR,
antivirus, whatever's already watching the environment. RAIN doesn't
try to replace any of that; the event bus is a built-in Syslog listener
(auto-detecting plain text, CEF, JSON, and Splunk-style key=value
bodies, no per-source configuration) rather than a growing list of
bespoke integrations, so pointing whatever's already generating alerts
at RAIN is enough to get started.

## Capabilities

- Landing page shows a welcome message, or a flagged document
- Incident, vulnerability, and change tickets, one shared record shape
- Drag-and-drop Kanban board, same tickets and filters as the list
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
- Runtime branding: instance name, accent color, logo, font, and custom
  JS for analytics/chat widgets
- Schema-per-tenant multi-tenancy on one Postgres instance
- Self-hosted, air-gapped-capable, no telemetry, no license server

See [`docs/user-guide.md`](docs/user-guide.md) for how each of these
actually works day to day, organized by the same sidebar you'll see in
the app; [`docs/architecture.md`](docs/architecture.md) for the
technical design and deployment lessons; [`docs/database-schema.md`](docs/database-schema.md)
for every table and how it relates to the rest; and
[`docs/code-layout.md`](docs/code-layout.md) for where things live in
the codebase and how to add to it.

## Quickstart

Requires Docker and Docker Compose. Nothing else.

```sh
python bootstrap.py      # or bootstrap.ps1 / bootstrap.sh -- generates .env once
docker compose up --build
```

`bootstrap` generates strong random secrets and asks a handful of
deployment questions (built-in vs external Postgres, local disk vs S3
document storage, a separate worker container vs merging it into `app`,
Caddy vs an existing reverse proxy) -- defaulting to the setup above if
you just press Enter. It only ever runs once; a `.env` that already
exists is left untouched.

Then visit `https://localhost` (Caddy issues a certificate
automatically). The first visit runs a setup wizard: instance name,
accent color, an optional logo, your first tenant, and the first
internal admin account. Everything else is configured afterwards from
the Admin console.

To feed the ticketing side, point a syslog-ng destination at this host
on `SYSLOG_PORT` (default `5514`, TCP or UDP) -- see
[`docs/architecture.md`](docs/architecture.md#ticketing)
for the destination snippet.

For an external/managed Postgres, S3 document storage, a single
merged-container deployment (`EMBED_WORKER=true`), or deploying without
Compose at all, see the comments in `.env.example` --
`docker-compose.minimal.yml` and `bootstrap` itself walk through the
same options interactively. For Kubernetes, see
[`charts/rain/README.md`](charts/rain/README.md) -- one Helm chart,
the same deployment shapes as the two Compose files.

## Stack

| Piece | Choice | Why |
|---|---|---|
| Frontend edge | Caddy (alpine) | Automatic HTTPS, reverse proxy, nothing else to configure |
| App | FastAPI + Jinja2, server-rendered | No Node/SPA build, no third-party JS framework to track for CVEs |
| DB | Postgres, optionally with pgvector | Full-text search (tsvector/GIN); pgvector is enabled by default but unused -- no vector/semantic search is planned |
| Multi-tenancy | Schema-per-tenant | One Postgres instance, isolated per tenant |
| Auth | Local email/password + optional LDAP + SAML 2.0 | `python3-saml` for SAML, not hand-rolled |
| Ticketing bus | Built-in syslog listener (TCP+UDP) | No third-party syslog library; foldable into the app container for a single-container deployment |
| Document storage | Local volume, or S3/S3-compatible | Swappable behind one small abstraction |
| Exports | CSV, JSON, Excel, PDF, iCalendar | All pure-Python, no extra system dependencies in the image |

See [`docs/code-layout.md`](docs/code-layout.md) for the repository
layout and module boundaries, and [`docs/architecture.md`](docs/architecture.md)
for the reasoning behind each of these choices.

## Development

```sh
cd backend
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
pytest                                            # pure-function tests, no DB needed
TEST_DATABASE_URL=postgresql+asyncpg://rain:rain@localhost:5432/rain_test pytest tests/test_integration.py
```

Alembic runs from `backend/` against whichever section you need, e.g.
`alembic -n control upgrade head` -- in the running app, migrations run
automatically at startup. Set `DEBUG=true` in `.env` for full
tracebacks inline in 500 responses; never set it true anywhere but a
local checkout -- see
[`docs/architecture.md`](docs/architecture.md#lessons-from-the-first-real-docker-run)
for why.

## Support

Commercial support plans, deployment assistance, and patch/update
cadences aligned with U.S. Government timeliness expectations for
security-relevant fixes are available. Reach out for details on support
tiers, SLAs, and delivery for air-gapped and controlled environments.

Contact: [inquiries@curated.systems](mailto:inquiries@curated.systems)
