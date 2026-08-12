"""Tenant lifecycle: creating a new tenant schema and keeping existing
tenant schemas caught up with the tenant migration chain."""
from __future__ import annotations

import re

from sqlalchemy import select, text

from rain.db import migrate
from rain.db.base import control_session
from rain.db.control_models import Tenant

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class InvalidSlugError(ValueError):
    pass


def schema_name_for(slug: str) -> str:
    return f"tenant_{slug}"


async def provision_tenant(*, slug: str, name: str) -> Tenant:
    """Create the control.tenants row, the Postgres schema, and bring it to
    the current tenant migration head. Raises InvalidSlugError on a bad
    slug; a duplicate slug raises the DB's unique-constraint IntegrityError."""
    if not _SLUG_RE.match(slug):
        raise InvalidSlugError("slug must be lowercase, start with a letter, and use only a-z 0-9 _")

    schema = schema_name_for(slug)

    async with control_session() as session:
        tenant = Tenant(slug=slug, name=name, schema_name=schema)
        session.add(tenant)
        await session.flush()
        await session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await session.commit()
        await session.refresh(tenant)

    await migrate.upgrade_tenant_async(schema)
    return tenant


async def reconcile_all_tenant_schemas() -> None:
    """Bring every active tenant schema up to the current migration head.
    Called at app startup so a code upgrade that adds tenant tables/columns
    doesn't require a manual per-tenant migration step."""
    async with control_session() as session:
        result = await session.execute(select(Tenant.schema_name).where(Tenant.is_active.is_(True)))
        schemas = list(result.scalars())

    for schema in schemas:
        await migrate.upgrade_tenant_async(schema)
