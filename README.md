# RAIN

RAIN is a self-hosted IT system of record: an asset registry today, with
syslog-driven ticketing and a document repository arriving in the next
milestones. It's containerized, multi-tenant, and configures itself at
runtime -- almost nothing lives in environment variables or config files.

This repository currently implements **Milestone 1**: the shared platform
(auth, multi-tenancy, DB-driven runtime config, branding, RBAC, tree
navigation, first-run setup wizard) plus the full **Asset Registry**
capability. See [`docs/architecture.md`](docs/architecture.md) for the
detailed design and the roadmap for Ticketing and Documents.

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
custom fields -- is configured afterwards from the Admin UI, stored in
Postgres.

## Stack

| Piece | Choice | Why |
|---|---|---|
| Frontend edge | Caddy (alpine) | Automatic HTTPS, reverse proxy, nothing else to configure |
| App | FastAPI + Jinja2, server-rendered | No Node/SPA build; the entire client-side footprint is one hand-written CSS file and one small vanilla-JS file (nav expand/collapse, a couple of `fetch()` calls) -- no htmx/Alpine/Tailwind dependency to track for CVEs |
| DB | Postgres 16 (alpine) + pgvector compiled in | pgvector installed now, unused until the future LLM search hook |
| Multi-tenancy | Schema-per-tenant | One Postgres instance, `control` schema for platform data, `tenant_<slug>` per tenant |
| Auth | Local email/password (Argon2, DB-backed sessions) | `control.auth_providers` already has disabled OIDC/SAML/LDAP rows, ready for a future release |

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
    modules/{setup,auth,admin,assets}/  -- one router+service per feature area
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

- **Milestone 2 -- Ticketing**: the `worker` container (currently a
  placeholder) becomes a syslog listener with a live viewer, a regex rule
  editor promoting events into `INC-xxxx`/`VULN-xxxx` tickets, and
  email/Slack notifications.
- **Milestone 3 -- Documents**: `DOC-xxxx` entries linkable to assets and
  tickets.
- **Future**: pgvector-backed keyword/vector search hook.
