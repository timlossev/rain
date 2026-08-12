"""Integration tests against a real Postgres. Point TEST_DATABASE_URL at a
scratch database (never a real deployment's DB -- schemas get dropped and
recreated). Run inside the dev stack, e.g.:

    docker compose run --rm -e TEST_DATABASE_URL=postgresql+asyncpg://rain:<pw>@db:5432/rain \
        app pytest tests/test_integration.py

Skipped automatically when TEST_DATABASE_URL isn't set (e.g. plain `pytest`
on a laptop with no Postgres running).
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL to a scratch Postgres to run integration tests",
)

if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-production")


@pytest.fixture(scope="module", autouse=True)
async def _clean_slate():
    from rain.db.base import dispose_engine, get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT nspname FROM pg_namespace WHERE nspname = 'control' OR nspname LIKE 'tenant_%'")
        )
        for (schema,) in result.all():
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    yield
    await dispose_engine()


async def test_control_migration_seeds_roles():
    from rain.db import migrate
    from rain.db.base import control_session
    from rain.db.control_models import Role

    await migrate.upgrade_control_async()

    async with control_session() as session:
        result = await session.execute(select(Role.key).order_by(Role.key))
        assert list(result.scalars()) == ["client", "internal_admin"]


async def test_tenant_provisioning_and_asset_crud():
    from rain.db import migrate
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import Asset, AssetType

    await migrate.upgrade_control_async()
    tenant = await provision_tenant(slug="acme", name="Acme Corp")
    assert tenant.schema_name == "tenant_acme"

    async with tenant_session(tenant.schema_name) as session:
        asset_type = AssetType(key="server", name="Server")
        session.add(asset_type)
        await session.flush()

        session.add(Asset(asset_type_id=asset_type.id, name="web-01", external_id="SN1"))
        await session.commit()

        result = await session.execute(select(Asset).where(Asset.external_id == "SN1"))
        asset = result.scalar_one()
        assert asset.name == "web-01"


async def test_reconcile_all_tenant_schemas_is_idempotent():
    from rain.db.provisioning import reconcile_all_tenant_schemas

    await reconcile_all_tenant_schemas()
    await reconcile_all_tenant_schemas()  # a second pass must not raise
