# RAIN

RAIN is a self-hosted IT system of record: an asset registry, syslog-driven
ticketing, and a document repository. It's containerized, multi-tenant, and
configures itself at runtime -- almost nothing lives in environment
variables or config files.

This repository implements all three planned milestones: **Milestone 1**
(the shared platform -- auth, multi-tenancy, DB-driven runtime config,
branding, RBAC, tree navigation, first-run setup wizard, full Asset
Registry), **Milestone 2** (Ticketing -- a real-time syslog viewer, regex
rule engine auto-promoting events into `INC-xxxx`/`VULN-xxxx` tickets,
email/Slack notifications), and **Milestone 3** (Documents -- `DOC-xxxx`
entries in a local-volume repository, linkable to assets and tickets).
See [`docs/architecture.md`](docs/architecture.md) for the detailed design
and the remaining roadmap (LLM search, cloud sync, OIDC/SAML/LDAP).

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
from the Admin UI, stored in Postgres.

To feed the ticketing side, point a syslog-ng destination at this host on
`SYSLOG_PORT` (default `5514`, TCP or UDP) -- Admin > Syslog Sources shows
the exact destination snippet and lets you map hosts/programs to tenants.

## Stack

| Piece | Choice | Why |
|---|---|---|
| Frontend edge | Caddy (alpine) | Automatic HTTPS, reverse proxy, nothing else to configure |
| App | FastAPI + Jinja2, server-rendered | No Node/SPA build; the entire client-side footprint is one hand-written CSS file and a couple of small vanilla-JS files (nav expand/collapse, a live WebSocket feed) -- no htmx/Alpine/Tailwind dependency to track for CVEs |
| DB | Postgres 16 (alpine) + pgvector compiled in | pgvector installed now, unused until the future LLM search hook |
| Multi-tenancy | Schema-per-tenant | One Postgres instance, `control` schema for platform data, `tenant_<slug>` per tenant |
| Auth | Local email/password (Argon2, DB-backed sessions) | `control.auth_providers` already has disabled OIDC/SAML/LDAP rows, ready for a future release |
| Ticketing bus | Hand-written syslog listener (TCP+UDP) in `worker` | No third-party syslog library; syslog-ng pushes to it as a `network()` destination |
| Document storage | Local volume behind a `StorageBackend` abstraction | Swappable for S3 later without touching callers; served only through an authenticated download route, never the static file mount |

Images are multi-stage and Alpine-based throughout; only Caddy's ports are
published to the host.

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
    modules/{setup,auth,admin,assets,tickets,documents}/  -- one router+service per feature area
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

## Roadmap

All three planned milestones are implemented. What's left, per
[`docs/architecture.md`](docs/architecture.md#roadmap):

- pgvector-backed keyword/vector search hook (pgvector is already
  installed, unused).
- Real AWS/Azure asset discovery (`SyncProvider.discover_assets()` is
  currently a stub).
- OIDC/SAML/LDAP auth providers (`control.auth_providers` rows already
  exist, disabled).
