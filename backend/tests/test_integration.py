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


async def test_ticket_custom_fields_scope_isolation_and_import_export():
    """A ticket-scoped CustomField and an asset-scoped one share one table
    (CustomField.scope) -- this covers the three things that break if that
    sharing ever leaks: assets.service.fields_for_type/all_fields still
    only see asset-scoped rows, tickets.service.ticket_fields only sees
    ticket-scoped ones, and a value written through set_ticket_field_values
    round-trips through both the exporter's field_<id> column and the
    importer's mapping the same way rain.modules.assets' own custom fields
    already do."""
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import AssetType, CustomField
    from rain.modules.assets import service as asset_service
    from rain.modules.tickets import exporter, importer, service

    tenant = await provision_tenant(slug="delta", name="Delta LLC")

    async with tenant_session(tenant.schema_name) as session:
        asset_type = AssetType(key="server", name="Server")
        session.add(asset_type)
        session.add(CustomField(scope="asset", asset_type_id=None, field_key="warranty", label="Warranty", field_type="text"))
        ticket_field = CustomField(scope="ticket", asset_type_id=None, field_key="cab_ref", label="CAB Reference", field_type="text")
        session.add(ticket_field)
        await session.commit()
        await session.refresh(ticket_field)

        # Scope isolation: each side only ever sees its own rows.
        asset_fields = await asset_service.all_fields(session)
        assert [f.field_key for f in asset_fields] == ["warranty"]
        ticket_fields = await service.ticket_fields(session)
        assert [f.field_key for f in ticket_fields] == ["cab_ref"]

        # Capture + round-trip through get_ticket's eager load.
        ticket = await service.create_ticket(session, ticket_type="incident", title="net outage", description=None)
        await service.set_ticket_field_values(session, ticket, {ticket_field.id: "CAB-4021"})
        await session.commit()

        reloaded = await service.get_ticket(session, ticket.id)
        assert reloaded is not None
        assert {fv.field_id: fv.value for fv in reloaded.field_values} == {ticket_field.id: "CAB-4021"}

        # Export: field_<id> column shows up and carries the value.
        columns = await exporter.available_columns(session)
        assert (f"field_{ticket_field.id}", "CAB Reference") in columns
        rows = await exporter.build_rows(
            session,
            ticket_type=None,
            status=None,
            columns=[{"source": "title", "header": "Title"}, {"source": f"field_{ticket_field.id}", "header": "CAB"}],
        )
        row = next(r for r in rows if r["Title"] == "net outage")
        assert row["CAB"] == "CAB-4021"

        # Import: a mapped column lands in TicketFieldValue for the new row.
        result = await importer.commit_import(
            session,
            rows=[{"Type": "incident", "Title": "imported ticket", "CAB": "CAB-9999"}],
            mapping={"ticket_type": "Type", "title": "Title", f"field_{ticket_field.id}": "CAB"},
            actor_id=None,
        )
        assert result.created == 1
        assert result.errors == []

        imported = await service.list_tickets(session, ticket_type="incident")
        imported_ticket = next(t for t in imported if t.title == "imported ticket")
        reloaded_imported = await service.get_ticket(session, imported_ticket.id)
        assert reloaded_imported is not None
        assert {fv.field_id: fv.value for fv in reloaded_imported.field_values} == {ticket_field.id: "CAB-9999"}

        # A change row is rejected rather than silently created without an
        # approval flow -- see rain.modules.tickets.importer's own docstring.
        change_result = await importer.commit_import(
            session,
            rows=[{"Type": "change", "Title": "should not import"}],
            mapping={"ticket_type": "Type", "title": "Title"},
            actor_id=None,
        )
        assert change_result.created == 0
        assert len(change_result.errors) == 1


async def test_document_tags_search_and_calendar_link():
    """Covers migration 0039's IMMUTABLE-function workaround for folding
    an array into a GENERATED tsvector (a search on a tag with nothing
    else matching still has to find the document), and 0040's plain
    CalendarEntry.document_id link (independent of the older policy_ref
    auto-refresh mechanism) plus its ON DELETE CASCADE."""
    import datetime as dt

    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import CalendarEntry
    from rain.modules.calendar import service as calendar_service
    from rain.modules.documents import service as document_service
    from rain.modules.search import service as search_service

    tenant = await provision_tenant(slug="kappa", name="Kappa Inc")

    async with tenant_session(tenant.schema_name) as session:
        doc = await document_service.create_document(
            session,
            title="Runbook: incident response",
            description="How we handle a P1.",
            filename="runbook.md",
            storage_key="kappa/runbook.md",
            mime_type="text/markdown",
            size_bytes=100,
            uploaded_by=None,
            tags=document_service.parse_tags("Security, security, oncall"),
        )
        await session.commit()
        assert doc.tags == ["Security", "oncall"]

        # A query matching only the tag, nothing in title/description.
        results = await search_service.search(session, "oncall")
        assert any(r.kind == "document" and r.id == doc.id for r in results)

        # The Documents list screen's own quick-search box matches tags too.
        list_hits = (
            await session.execute(document_service.document_list_stmt(search="oncall"))
        ).scalars().all()
        assert any(d.id == doc.id for d in list_hits)

        # Calendar link: a plain reminder, no auto-refresh policy.
        entry = await calendar_service.create_entry(
            session,
            title="Quarterly revision",
            description=None,
            start_date=dt.date(2026, 1, 1),
            recurrence="quarterly",
            recurrence_end=None,
            emit_syslog_event=False,
            event_program=None,
            document_id=doc.id,
            policy_ref=None,
            created_by=None,
        )
        await session.commit()

        for_doc = await calendar_service.list_entries_for_document(session, doc.id)
        assert [e.id for e in for_doc] == [entry.id]

        # Deleting the document cascades to its linked reminder.
        await document_service.delete_document(session, doc)
        remaining = await session.get(CalendarEntry, entry.id)
        assert remaining is None
