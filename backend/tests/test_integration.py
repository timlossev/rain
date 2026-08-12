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


async def test_ticket_numbering_and_rule_promotion():
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import SyslogEvent, TicketRule
    from rain.modules.tickets import rules, service

    tenant = await provision_tenant(slug="beta", name="Beta Inc")

    async with tenant_session(tenant.schema_name) as session:
        t1 = await service.create_ticket(session, ticket_type="incident", title="first", description=None)
        t2 = await service.create_ticket(session, ticket_type="incident", title="second", description=None)
        v1 = await service.create_ticket(session, ticket_type="vulnerability", title="vuln", description=None)

        assert t1.ticket_number == "INC-000001"
        assert t2.ticket_number == "INC-000002"
        assert v1.ticket_number == "VULN-000001"

        session.add(
            TicketRule(name="su fail", ticket_type="incident", match_field="message", pattern="failed", severity="high")
        )
        await session.commit()

        event = SyslogEvent(
            host="web-01", program="su", facility=4, severity=2, message="failed password", raw="raw line"
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        matched = await rules.find_matching_rule(session, event)
        assert matched is not None

        ticket = await rules.apply_rule(session, matched, event)
        assert ticket.ticket_number == "INC-000003"
        assert ticket.source_event_id == event.id

        await session.refresh(event)
        assert event.promoted_ticket_id == ticket.id


async def test_syslog_source_routing():
    from rain.db.base import control_session
    from rain.db.control_models import SyslogSourceMap, Tenant
    from rain.modules.tickets.routing import resolve_tenant_for_event

    async with control_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.slug == "beta"))
        tenant = result.scalar_one()
        session.add(SyslogSourceMap(tenant_id=tenant.id, match_field="host", pattern=r"^web-\d+$", is_regex=True))
        await session.commit()

    async with control_session() as session:
        resolved = await resolve_tenant_for_event(session, host="web-42", program=None)
        assert resolved is not None
        assert resolved.slug == "beta"

        resolved_none = await resolve_tenant_for_event(session, host="db-01", program=None)
        assert resolved_none is None


async def test_document_numbering_and_linking():
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import Asset, AssetType
    from rain.modules.documents import service as document_service

    tenant = await provision_tenant(slug="gamma", name="Gamma LLC")

    async with tenant_session(tenant.schema_name) as session:
        asset_type = AssetType(key="server", name="Server")
        session.add(asset_type)
        await session.flush()
        asset = Asset(asset_type_id=asset_type.id, name="web-01")
        session.add(asset)
        await session.commit()
        await session.refresh(asset)

        doc1 = await document_service.create_document(
            session, title="Runbook", description=None, filename="runbook.pdf",
            storage_key="gamma/abc-runbook.pdf", mime_type="application/pdf", size_bytes=1024, uploaded_by=None,
        )
        doc2 = await document_service.create_document(
            session, title="Postmortem", description=None, filename="pm.md",
            storage_key="gamma/def-pm.md", mime_type="text/markdown", size_bytes=512, uploaded_by=None,
        )
        assert doc1.doc_number == "DOC-000001"
        assert doc2.doc_number == "DOC-000002"

        await document_service.add_link(session, doc1.id, "asset", asset.id, None)
        links = await document_service.links_for(session, "asset", asset.id)
        assert len(links) == 1
        assert links[0].document.doc_number == "DOC-000001"

        found = await document_service.get_document(session, doc1.id)
        assert found is not None
        await document_service.delete_document(session, found)

        assert await document_service.links_for(session, "asset", asset.id) == []
