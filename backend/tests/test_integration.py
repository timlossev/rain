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

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="set TEST_DATABASE_URL to a scratch Postgres to run integration tests",
    ),
    # One event loop for every test in this module, not pytest-asyncio's
    # own function-scoped default -- rain.db.base.get_engine() caches one
    # AsyncEngine (and its asyncpg connection pool) at module-global
    # scope, and _clean_slate below is itself a module-scoped fixture
    # (one drop-and-recreate per module, not per test). A fresh loop per
    # test function meant every test past the first one inherited pool
    # connections still bound to an already-closed loop from an earlier
    # test -- confirmed live against a real Postgres (the very first time
    # this suite ever actually ran end to end; previously reviewed but
    # never executed, since no Postgres was ever available before).
    pytest.mark.asyncio(loop_scope="module"),
]

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
        assert list(result.scalars()) == ["client", "client_admin", "internal_admin"]


async def test_tenant_provisioning_and_asset_crud():
    from rain.db import migrate
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import Asset, AssetType
    from rain.modules.assets.service import next_ci_number

    await migrate.upgrade_control_async()
    tenant = await provision_tenant(slug="acme", name="Acme Corp")
    assert tenant.schema_name == "tenant_acme"

    async with tenant_session(tenant.schema_name) as session:
        asset_type = AssetType(key="server", name="Server")
        session.add(asset_type)
        await session.flush()

        ci_number = await next_ci_number(session)
        session.add(Asset(ci_number=ci_number, asset_type_id=asset_type.id, name="web-01", external_id="SN1"))
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
        # resolve_tenant_for_event returns a RoutingResult, not a bare
        # Tenant -- .tenant is None either for a genuine no-match or a
        # deliberate "discard" rule (.discarded distinguishes the two);
        # neither case applies here, just a plain route match/non-match.
        resolved = await resolve_tenant_for_event(session, host="web-42", program=None)
        assert resolved.tenant is not None
        assert resolved.tenant.slug == "beta"

        resolved_none = await resolve_tenant_for_event(session, host="db-01", program=None)
        assert resolved_none.tenant is None


async def test_document_numbering_and_linking():
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import Asset, AssetType
    from rain.modules.assets.service import next_ci_number
    from rain.modules.documents import service as document_service

    tenant = await provision_tenant(slug="gamma", name="Gamma LLC")

    async with tenant_session(tenant.schema_name) as session:
        asset_type = AssetType(key="server", name="Server")
        session.add(asset_type)
        await session.flush()
        ci_number = await next_ci_number(session)
        asset = Asset(ci_number=ci_number, asset_type_id=asset_type.id, name="web-01")
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

        # Deleting the document cascades to its linked reminder. The DB
        # does the actual cascading (ON DELETE CASCADE), not the ORM --
        # session.get()'s default identity-map-first lookup would just
        # hand back the same still-cached Python object regardless,
        # populate_existing=True forces a real round-trip to confirm the
        # row is actually gone.
        await document_service.delete_document(session, doc)
        remaining = await session.get(CalendarEntry, entry.id, populate_existing=True)
        assert remaining is None


async def test_platform_event_rule_fires_matching_actions_only():
    """rain.modules.tickets.platform_events end to end: create_ticket's own
    hook into evaluate_ticket_created, an active rule's actions actually
    running (mark_problematic, add_watcher by email), the firing logged
    both to platform_event_triggers and the ticket's own activity feed --
    and, just as importantly, that a non-matching and an inactive rule
    both correctly do *not* fire."""
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import PlatformEventAction, PlatformEventRule, PlatformEventTrigger, TicketFieldChange, TicketWatcher
    from rain.modules.tickets import service

    tenant = await provision_tenant(slug="lambda", name="Lambda LLC")

    async with tenant_session(tenant.schema_name) as session:
        matching_rule = PlatformEventRule(name="Major outage", trigger_event="incident_created", match_field="title", pattern="outage")
        matching_rule.actions.append(PlatformEventAction(action_type="mark_problematic", config={}))
        matching_rule.actions.append(PlatformEventAction(action_type="add_watcher", config={"email": "oncall@example.com"}))
        session.add(matching_rule)

        non_matching_rule = PlatformEventRule(name="Disk full", trigger_event="incident_created", match_field="title", pattern="disk full")
        non_matching_rule.actions.append(PlatformEventAction(action_type="mark_problematic", config={}))
        session.add(non_matching_rule)

        inactive_rule = PlatformEventRule(
            name="Inactive outage rule", trigger_event="incident_created", match_field="title", pattern="outage", is_active=False
        )
        inactive_rule.actions.append(PlatformEventAction(action_type="add_watcher", config={"email": "should-not-be-added@example.com"}))
        session.add(inactive_rule)
        await session.commit()

        ticket = await service.create_ticket(session, ticket_type="incident", title="major outage in us-east", description=None)

        reloaded = await service.get_ticket(session, ticket.id)
        assert reloaded is not None
        assert reloaded.is_problematic is True

        watchers = (await session.execute(select(TicketWatcher).where(TicketWatcher.ticket_id == ticket.id))).scalars().all()
        assert [w.email for w in watchers] == ["oncall@example.com"]

        triggers = (
            await session.execute(select(PlatformEventTrigger).where(PlatformEventTrigger.ticket_id == ticket.id))
        ).scalars().all()
        assert [t.rule_name for t in triggers] == ["Major outage"]
        assert "Mark problematic" in triggers[0].summary
        assert "oncall@example.com" in triggers[0].summary

        field_changes = (
            await session.execute(select(TicketFieldChange).where(TicketFieldChange.ticket_id == ticket.id, TicketFieldChange.field_name == "platform_rule"))
        ).scalars().all()
        assert len(field_changes) == 1


async def test_escalate_ticket_captures_webhook_response_as_comment(monkeypatch):
    """rain.modules.tickets.service.escalate_ticket: both log lines it's
    documented to produce (the terse field-change entry, unchanged from
    before this session's rebuild, and the new rich comment carrying the
    webhook's actual response body), plus the _ESCALATION_BODY_MAX_CHARS
    truncation on an oversized response. webhook_service.call_webhook is
    monkeypatched rather than actually dispatched -- this is exercising
    escalate_ticket's own logging/comment logic, not the HTTP client."""
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import TicketComment, TicketFieldChange, WebhookConfig
    from rain.modules.tickets import service
    from rain.modules.webhooks import service as webhook_service

    tenant = await provision_tenant(slug="mu", name="Mu Inc")

    async with tenant_session(tenant.schema_name) as session:
        webhook = WebhookConfig(name="PagerDuty", url="https://example.com/hook")
        session.add(webhook)
        ticket = await service.create_ticket(session, ticket_type="incident", title="db down", description=None)
        await session.commit()
        await session.refresh(webhook)

        async def fake_call_webhook(config, placeholders=None):
            return webhook_service.WebhookResult(status_code=200, success=True, body="ack: paged on-call")

        monkeypatch.setattr(webhook_service, "call_webhook", fake_call_webhook)
        outcome = await service.escalate_ticket(session, ticket, webhook, actor_user_id=None)

        assert outcome.success is True
        assert outcome.status_code == 200
        assert outcome.body == "ack: paged on-call"

        field_changes = (
            await session.execute(select(TicketFieldChange).where(TicketFieldChange.ticket_id == ticket.id, TicketFieldChange.field_name == "escalated"))
        ).scalars().all()
        assert len(field_changes) == 1
        assert "PagerDuty" in field_changes[0].to_value
        assert "HTTP 200" in field_changes[0].to_value

        comments = (await session.execute(select(TicketComment).where(TicketComment.ticket_id == ticket.id))).scalars().all()
        assert len(comments) == 1
        assert "ack: paged on-call" in comments[0].body

        # A response body over the cap gets truncated, not dropped or left
        # to blow up the comment/activity feed.
        async def fake_call_webhook_oversized(config, placeholders=None):
            return webhook_service.WebhookResult(status_code=200, success=True, body="x" * (service._ESCALATION_BODY_MAX_CHARS + 500))

        monkeypatch.setattr(webhook_service, "call_webhook", fake_call_webhook_oversized)
        await service.escalate_ticket(session, ticket, webhook, actor_user_id=None)

        comments = (await session.execute(select(TicketComment).where(TicketComment.ticket_id == ticket.id))).scalars().all()
        assert len(comments) == 2
        newest = comments[-1]
        assert "(truncated)" in newest.body
        assert len(newest.body) < service._ESCALATION_BODY_MAX_CHARS + 500


async def test_rootcause_auto_analyze_and_platform_rule_on_close():
    """Two independent close-time reactions covered together, both wired
    through rain.modules.tickets.service.update_status's single
    newly_closed branch: rootcause.analyze's opt-in auto-comment (gated
    by the auto_root_cause_on_close tenant config) summarizing the
    ticket's repeat promoted syslog events, and an active "incident is
    closed" Platform Response Rule's own action firing alongside it."""
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import PlatformEventAction, PlatformEventRule, SyslogEvent, TicketComment
    from rain.core.tenant_config import set_tenant_config
    from rain.modules.tickets import rootcause, service

    tenant = await provision_tenant(slug="nu", name="Nu Corp")

    async with tenant_session(tenant.schema_name) as session:
        await set_tenant_config(session, rootcause.AUTO_ROOT_CAUSE_CONFIG_KEY, True)

        closed_rule = PlatformEventRule(name="Outage closed", trigger_event="incident_closed", match_field="title", pattern="outage")
        closed_rule.actions.append(PlatformEventAction(action_type="mark_problematic", config={}))
        session.add(closed_rule)

        ticket = await service.create_ticket(session, ticket_type="incident", title="recurring outage", description=None)

        # Two promoted syslog events -- summarize_chronic only produces a
        # summary once there's more than one (see that function's own
        # docstring), which is also the exact condition this covers.
        event1 = SyslogEvent(host="web-01", program="nginx", facility=1, severity=3, message="502", raw="raw1", promoted_ticket_id=ticket.id)
        event2 = SyslogEvent(host="web-01", program="nginx", facility=1, severity=3, message="502", raw="raw2", promoted_ticket_id=ticket.id)
        session.add_all([event1, event2])
        await session.commit()
        await session.refresh(event1)
        await session.refresh(event2)

        ok = await service.update_status(session, ticket, "closed")
        assert ok is True

        reloaded = await service.get_ticket(session, ticket.id)
        assert reloaded is not None
        assert reloaded.status == "closed"
        assert reloaded.is_problematic is True  # the "incident_closed" platform rule's own action

        comments = (await session.execute(select(TicketComment).where(TicketComment.ticket_id == ticket.id))).scalars().all()
        assert len(comments) == 1
        assert "Root cause assistance" in comments[0].body
        assert "Repetition pattern" in comments[0].body
        assert "web-01" in comments[0].body

        # A later closed -> closed move (e.g. Closed -> Cancelled, if this
        # tenant had one) must not fire either reaction again -- covered
        # here by re-closing into the same status, which update_status's
        # own new_status == ticket.status guard short-circuits before the
        # newly_closed check is even reached.
        again = await service.update_status(session, ticket, "closed")
        assert again is True
        comments_after = (await session.execute(select(TicketComment).where(TicketComment.ticket_id == ticket.id))).scalars().all()
        assert len(comments_after) == 1


async def test_tenant_config_bundle_round_trips_across_tenants():
    """rain.modules.admin.config_bundle's tenant bundle, exercised through
    its hardest interdependent path: a group with a local-user member, an
    approval flow whose one step is assigned to that group, an event
    policy and a Service Catalog item that both reference the flow by
    name, and a Platform Response Rule whose actions reference a webhook
    and a notification channel -- every one of those is a raw database id
    in the source tenant and has to come out the other end resolved by
    name against a *different* tenant's own freshly-created rows. Also
    proves the bundle is genuinely JSON round-trippable (not just a
    Python dict) and that re-importing the same bundle upserts instead of
    duplicating."""
    import json

    from rain.core.crypto import decrypt_json, encrypt_json
    from rain.core.security import hash_password
    from rain.db.base import control_session, tenant_session
    from rain.db.control_models import User
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import (
        ApprovalFlow,
        ApprovalFlowStep,
        AssetType,
        Group,
        GroupMembership,
        NotificationChannel,
        PlatformEventAction,
        PlatformEventRule,
        ServiceCatalogItem,
        TicketRule,
        WebhookConfig,
    )
    from rain.modules.admin import config_bundle

    source = await provision_tenant(slug="xi", name="Xi Source")
    target = await provision_tenant(slug="omicron", name="Omicron Target")

    async with control_session() as control_db:
        source_user = User(
            tenant_id=source.id, email="oncall@xi.example", password_hash=hash_password("correct horse battery staple"),
            role_key="client", display_name="On-call", auth_source="local",
        )
        control_db.add(source_user)
        await control_db.commit()

    async with tenant_session(source.schema_name) as session:
        group = Group(name="On-call")
        session.add(group)
        await session.flush()
        session.add(GroupMembership(group_id=group.id, user_id=source_user.id))

        flow = ApprovalFlow(name="Standard change")
        session.add(flow)
        await session.flush()
        session.add(ApprovalFlowStep(flow_id=flow.id, sort_order=0, label="On-call approval", approver_group_id=group.id))

        webhook = WebhookConfig(name="Escalation hook", url="https://example.com/hook", headers={"Authorization": "Bearer secret"})
        session.add(webhook)
        session.add(TicketRule(name="Prod outage", ticket_type="change", pattern="outage", approval_flow_id=flow.id))
        session.add(ServiceCatalogItem(key="new-user", name="Provision new user", ticket_type="incident", approval_flow_id=flow.id))
        await session.flush()

        channel = NotificationChannel(channel_type="webhook", name="Escalation channel", config_encrypted=encrypt_json({"webhook_id": webhook.id}))
        session.add(channel)
        await session.flush()

        rule = PlatformEventRule(name="Notify on outage", trigger_event="incident_created", match_field="title", pattern="outage")
        session.add(rule)
        await session.flush()
        session.add(PlatformEventAction(rule_id=rule.id, action_type="webhook", config={"webhook_id": webhook.id}))
        session.add(PlatformEventAction(rule_id=rule.id, action_type="notify_slack", config={"channel_id": channel.id}))
        session.add(AssetType(key="server", name="Server"))
        await session.commit()

        bundle = await config_bundle.build_tenant_bundle(session, source, include_secrets=True)

    # Genuinely JSON round-trippable, not just a Python dict in memory.
    reloaded = json.loads(json.dumps(bundle))
    assert reloaded["groups"][0]["name"] == "On-call"
    assert reloaded["approval_flows"][0]["steps"][0]["approver_group_name"] == "On-call"
    assert reloaded["event_policies"][0]["approval_flow_name"] == "Standard change"
    assert reloaded["service_catalog"][0]["approval_flow_name"] == "Standard change"
    assert reloaded["notification_channels"][0]["config"] == {"webhook_name": "Escalation hook"}
    actions = {a["action_type"]: a for a in reloaded["platform_response_rules"][0]["actions"]}
    assert actions["webhook"]["webhook_name"] == "Escalation hook"
    assert actions["notify_slack"]["channel_name"] == "Escalation channel"

    # Email is unique *instance-wide* (control.users' own uq_users_email),
    # not per-tenant -- source_user has to be gone before import, the same
    # way it would already be absent importing onto a genuinely different
    # instance (this bundle format's actual primary use case), or
    # apply_tenant_bundle correctly refuses to create a second account
    # under the same email for a different tenant (see its own comment).
    async with control_session() as control_db:
        await control_db.delete(await control_db.get(User, source_user.id))
        await control_db.commit()

    async with tenant_session(target.schema_name) as session:
        result = await config_bundle.apply_tenant_bundle(session, target, reloaded, updated_by=None)
        assert result.counts.get("asset types") == 1
        assert result.counts.get("groups") == 1
        assert result.counts.get("local users") == 1
        assert result.counts.get("group memberships") == 1
        assert result.counts.get("approval flows") == 1
        assert result.counts.get("approval flow steps") == 1
        assert result.counts.get("webhooks") == 1
        assert result.counts.get("event policies") == 1
        assert result.counts.get("service catalog items") == 1
        assert result.counts.get("notification channels") == 1
        assert result.counts.get("platform response rules") == 1
        assert result.counts.get("platform response rule actions") == 2

        target_group = (await session.execute(select(Group).where(Group.name == "On-call"))).scalar_one()
        target_flow = (await session.execute(select(ApprovalFlow).where(ApprovalFlow.name == "Standard change"))).scalar_one()
        steps = (await session.execute(select(ApprovalFlowStep).where(ApprovalFlowStep.flow_id == target_flow.id))).scalars().all()
        assert len(steps) == 1
        assert steps[0].approver_group_id == target_group.id

        target_rule = (await session.execute(select(TicketRule).where(TicketRule.name == "Prod outage"))).scalar_one()
        assert target_rule.approval_flow_id == target_flow.id

        target_catalog_item = (await session.execute(select(ServiceCatalogItem).where(ServiceCatalogItem.key == "new-user"))).scalar_one()
        assert target_catalog_item.approval_flow_id == target_flow.id

        target_channel = (await session.execute(select(NotificationChannel).where(NotificationChannel.name == "Escalation channel"))).scalar_one()
        target_webhook = (await session.execute(select(WebhookConfig).where(WebhookConfig.name == "Escalation hook"))).scalar_one()
        assert decrypt_json(target_channel.config_encrypted) == {"webhook_id": target_webhook.id}

        # Re-importing the same bundle upserts rather than duplicating.
        result2 = await config_bundle.apply_tenant_bundle(session, target, reloaded, updated_by=None)
        assert result2.counts.get("groups") is None
        assert result2.counts.get("groups (updated)") == 1
        assert result2.warnings, "re-importing the same local user should warn it already exists"
        all_groups = (await session.execute(select(Group))).scalars().all()
        assert len(all_groups) == 1


async def test_platform_config_bundle_redacts_secrets_by_default():
    """rain.modules.admin.config_bundle's platform bundle: without
    include_secrets, the LDAP bind password comes back redacted (empty,
    flagged) rather than either the real cleartext or the source
    instance's Fernet ciphertext (which would be undecryptable garbage on
    a different instance's own APP_SECRET_KEY-derived key anyway). With
    include_secrets, the real password round-trips."""
    from rain.db.base import control_session
    from rain.modules.admin import config_bundle
    from rain.modules.auth import ldap_config

    async with control_session() as session:
        await ldap_config.save_ldap_config(
            session,
            is_enabled=True,
            server_uri="ldaps://dc.example.internal",
            bind_dn="cn=svc,dc=example",
            bind_password="hunter2",
            target_tenant_id=None,
        )

    redacted = await config_bundle.build_platform_bundle(include_secrets=False)
    assert redacted["ldap"]["bind_password"] == ""
    assert redacted["ldap"]["password_redacted"] is True
    assert redacted["ldap"]["server_uri"] == "ldaps://dc.example.internal"
    assert any("LDAP bind password redacted" in w for w in redacted["warnings"])

    full = await config_bundle.build_platform_bundle(include_secrets=True)
    assert full["ldap"]["bind_password"] == "hunter2"
    assert "password_redacted" not in full["ldap"]


async def test_list_assignable_users_scopes_by_tenant_and_active():
    """rain.core.user_names.list_assignable_users backs Kanban's "group by
    assignee" columns (rain.modules.tickets.router.kanban_board) -- it has
    to return exactly the same candidate set is_assignable_user would
    accept a write for, or a column could exist for someone a drag-drop
    assignment then rejects. Covers the three ways that set is scoped:
    this tenant's own active users, every active internal_admin
    regardless of tenant, and NOT another tenant's users or a deactivated
    one of this tenant's own."""
    from rain.core.security import hash_password
    from rain.core.user_names import is_assignable_user, list_assignable_users
    from rain.db.base import control_session
    from rain.db.control_models import User
    from rain.db.provisioning import provision_tenant

    tenant_a = await provision_tenant(slug="pi", name="Pi Corp")
    tenant_b = await provision_tenant(slug="rho", name="Rho Corp")

    async with control_session() as session:
        own_active = User(
            tenant_id=tenant_a.id, email="agent@pi.example", password_hash=hash_password("x"),
            role_key="client", display_name="Pi Agent", auth_source="local", is_active=True,
        )
        own_inactive = User(
            tenant_id=tenant_a.id, email="gone@pi.example", password_hash=hash_password("x"),
            role_key="client", display_name="Pi Former Agent", auth_source="local", is_active=False,
        )
        other_tenant = User(
            tenant_id=tenant_b.id, email="agent@rho.example", password_hash=hash_password("x"),
            role_key="client", display_name="Rho Agent", auth_source="local", is_active=True,
        )
        admin = User(
            tenant_id=None, email="root@instance.example", password_hash=hash_password("x"),
            role_key="internal_admin", display_name="Root Admin", auth_source="local", is_active=True,
        )
        session.add_all([own_active, own_inactive, other_tenant, admin])
        await session.commit()

        candidates = await list_assignable_users(tenant_a.id)
        names = {u.display_name for u in candidates}
        assert names == {"Pi Agent", "Root Admin"}

        assert await is_assignable_user(own_active.id, tenant_a.id) is True
        assert await is_assignable_user(admin.id, tenant_a.id) is True
        assert await is_assignable_user(own_inactive.id, tenant_a.id) is False
        assert await is_assignable_user(other_tenant.id, tenant_a.id) is False


async def test_document_list_tag_filter_and_flag_lookups():
    """rain.modules.documents.service.list_all_tags/document_list_stmt's
    tag filter, and calendar.service.document_ids_with_calendar_entries --
    the three pieces backing the Documents list's tag dropdown and
    calendar-icon flag. Covers the one sharp edge in the tag filter: exact
    membership (Document.tags.any), not a substring match the way the
    list's own search box treats tags -- "Q4" must not also match a
    document only tagged "Q4-2026"."""
    import datetime as dt

    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.modules.calendar import service as calendar_service
    from rain.modules.documents import service as document_service

    tenant = await provision_tenant(slug="sigma", name="Sigma LLC")

    async with tenant_session(tenant.schema_name) as session:
        doc1 = await document_service.create_document(
            session, title="Runbook", description=None, filename="runbook.md",
            storage_key="sigma/runbook.md", mime_type="text/markdown", size_bytes=10, uploaded_by=None,
            tags=document_service.parse_tags("security, Q4-2026"),
        )
        doc2 = await document_service.create_document(
            session, title="Postmortem", description=None, filename="pm.md",
            storage_key="sigma/pm.md", mime_type="text/markdown", size_bytes=10, uploaded_by=None,
            tags=document_service.parse_tags("security, oncall"),
        )
        await session.commit()

        # A set comparison, not an exact ordered list -- list_all_tags'
        # ORDER BY is a real SQL clause (worth keeping), but which of
        # "Q4-2026" and "oncall" sorts first depends on the database's
        # collation, not on anything this test should be pinning down.
        assert set(await document_service.list_all_tags(session)) == {"Q4-2026", "oncall", "security"}

        security_docs = (await session.execute(document_service.document_list_stmt(tag="security"))).scalars().all()
        assert {d.id for d in security_docs} == {doc1.id, doc2.id}

        # Exact membership: "Q4" alone must not pull in "Q4-2026".
        exact_only = (await session.execute(document_service.document_list_stmt(tag="Q4"))).scalars().all()
        assert exact_only == []
        exact_match = (await session.execute(document_service.document_list_stmt(tag="Q4-2026"))).scalars().all()
        assert [d.id for d in exact_match] == [doc1.id]

        assert await calendar_service.document_ids_with_calendar_entries(session) == set()

        await calendar_service.create_entry(
            session, title="Quarterly review", description=None, start_date=dt.date(2026, 1, 1),
            recurrence="quarterly", recurrence_end=None, emit_syslog_event=False, event_program=None,
            document_id=doc1.id, policy_ref=None, created_by=None,
        )

        assert await calendar_service.document_ids_with_calendar_entries(session) == {doc1.id}


async def test_document_retag_and_owner_assignment():
    """rain.modules.documents.service.retag/update_owner -- the two writes
    behind the Documents Kanban board's drag-and-drop (documents_kanban's
    "group by tag"/"group by owner" modes). retag is the one with real
    edge-case risk: a targeted swap (remove one tag, add another) that
    must leave every other tag on the document untouched, and must merge
    rather than duplicate when the destination tag is one the document
    already carries under a different raw casing."""
    from rain.core.security import hash_password
    from rain.db.base import control_session, tenant_session
    from rain.db.control_models import User
    from rain.db.provisioning import provision_tenant
    from rain.modules.documents import service as document_service

    tenant = await provision_tenant(slug="upsilon", name="Upsilon Inc")

    async with control_session() as control_db:
        owner = User(
            tenant_id=tenant.id, email="owner@upsilon.example", password_hash=hash_password("x"),
            role_key="client", display_name="Doc Owner", auth_source="local",
        )
        control_db.add(owner)
        await control_db.commit()
        await control_db.refresh(owner)

    async with tenant_session(tenant.schema_name) as session:
        doc = await document_service.create_document(
            session, title="Runbook", description=None, filename="runbook.md",
            storage_key="upsilon/runbook.md", mime_type="text/markdown", size_bytes=10, uploaded_by=None,
            tags=document_service.parse_tags("security, OnCall"),
        )
        await session.commit()

        # A targeted swap: "OnCall" -> "Compliance" leaves "security" alone.
        await document_service.retag(session, doc, from_tag="OnCall", to_tag="Compliance")
        assert doc.tags == ["security", "Compliance"]

        # Dropping onto a tag the document already carries (case-
        # insensitively, via normalize_tag) merges instead of duplicating.
        await document_service.retag(session, doc, from_tag="security", to_tag="compliance")
        assert doc.tags == ["Compliance"]

        # Dropping into "Uncategorized" (empty to_tag) just removes.
        await document_service.retag(session, doc, from_tag="Compliance", to_tag="")
        assert doc.tags == []

        assert doc.owner_user_id is None
        await document_service.update_owner(session, doc, owner.id)
        assert doc.owner_user_id == owner.id
        await document_service.update_owner(session, doc, None)
        assert doc.owner_user_id is None


async def test_document_review_date_and_acknowledgment():
    """rain.modules.documents.service.update_review_date/acknowledge_document/
    list_acknowledgments -- the review-due and read-acknowledgment evidence
    documented in docs/eucs-compliance-assessment.md and docs/
    itsm-controls-mapping.md. Two edge cases worth pinning down: the
    overdue-only filter must never match a document with no review date
    set at all (untracked isn't the same as overdue), and re-acknowledging
    must update the existing row's timestamp rather than add a second one
    for the same person."""
    import datetime as dt

    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.modules.documents import service as document_service

    tenant = await provision_tenant(slug="tau", name="Tau Systems")

    async with tenant_session(tenant.schema_name) as session:
        overdue_doc = await document_service.create_document(
            session, title="Access Policy", description=None, filename="access-policy.md",
            storage_key="tau/access-policy.md", mime_type="text/markdown", size_bytes=10, uploaded_by=None, tags=[],
        )
        untracked_doc = await document_service.create_document(
            session, title="Runbook", description=None, filename="runbook.md",
            storage_key="tau/runbook.md", mime_type="text/markdown", size_bytes=10, uploaded_by=None, tags=[],
        )
        future_doc = await document_service.create_document(
            session, title="Onboarding", description=None, filename="onboarding.md",
            storage_key="tau/onboarding.md", mime_type="text/markdown", size_bytes=10, uploaded_by=None, tags=[],
        )
        await session.commit()

        today = dt.datetime.now(dt.timezone.utc).date()
        await document_service.update_review_date(session, overdue_doc, today - dt.timedelta(days=1))
        await document_service.update_review_date(session, future_doc, today + dt.timedelta(days=30))
        # untracked_doc's next_review_at is left unset entirely.

        overdue_only = (await session.execute(document_service.document_list_stmt(overdue_only=True))).scalars().all()
        assert [d.id for d in overdue_only] == [overdue_doc.id]

        # Clearing a review date (blank form submission) takes it back out
        # of the overdue set.
        await document_service.update_review_date(session, overdue_doc, None)
        overdue_only = (await session.execute(document_service.document_list_stmt(overdue_only=True))).scalars().all()
        assert overdue_only == []

        assert await document_service.list_acknowledgments(session, untracked_doc.id) == []
        await document_service.acknowledge_document(session, untracked_doc.id, user_id=101)
        first = (await document_service.list_acknowledgments(session, untracked_doc.id))[0]
        assert first.user_id == 101

        # Re-acknowledging updates acknowledged_at in place rather than
        # adding a second row for the same (document, user).
        await document_service.acknowledge_document(session, untracked_doc.id, user_id=101)
        again = await document_service.list_acknowledgments(session, untracked_doc.id)
        assert len(again) == 1
        assert again[0].acknowledged_at >= first.acknowledged_at

        # A different user acknowledging the same document adds a second,
        # distinct row.
        await document_service.acknowledge_document(session, untracked_doc.id, user_id=202)
        assert {a.user_id for a in await document_service.list_acknowledgments(session, untracked_doc.id)} == {101, 202}


async def test_document_acknowledgment_requirement_end_to_end():
    """rain.modules.documents.service.request_acknowledgment end to end --
    the document equivalent of test_platform_event_rule_fires_matching_
    actions_only above: a group-assigned requirement resolves to its
    members, shows up on list_documents_pending_acknowledgment_for (the
    client portal's Pending Actions query) for each of them, fires the
    document_pending_acknowledgment Platform Response Rule trigger
    (including a ticket-only action correctly skipping itself rather than
    erroring), acknowledging clears a member's own pending status without
    clearing anyone else's, and re-requesting puts an already-acknowledged
    member back on the pending list."""
    from rain.core.security import hash_password
    from rain.db.base import control_session, tenant_session
    from rain.db.control_models import User
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import Group, GroupMembership, PlatformEventAction, PlatformEventRule, PlatformEventTrigger
    from rain.modules.documents import service as document_service

    tenant = await provision_tenant(slug="phi", name="Phi Holdings")

    async with control_session() as control_db:
        reviewer_a = User(
            tenant_id=tenant.id, email="reviewer-a@phi.example", password_hash=hash_password("x"),
            role_key="client", display_name="Reviewer A", auth_source="local",
        )
        reviewer_b = User(
            tenant_id=tenant.id, email="reviewer-b@phi.example", password_hash=hash_password("x"),
            role_key="client", display_name="Reviewer B", auth_source="local",
        )
        control_db.add_all([reviewer_a, reviewer_b])
        await control_db.commit()
        await control_db.refresh(reviewer_a)
        await control_db.refresh(reviewer_b)

    async with tenant_session(tenant.schema_name) as session:
        group = Group(name="Reviewers", source="local")
        session.add(group)
        await session.flush()
        session.add_all(
            [
                GroupMembership(group_id=group.id, user_id=reviewer_a.id),
                GroupMembership(group_id=group.id, user_id=reviewer_b.id),
            ]
        )

        # A ticket-only action on a document-triggered rule -- should skip
        # itself (see platform_events._TICKET_ONLY_ACTIONS) rather than
        # raise, and say so in the logged summary.
        rule = PlatformEventRule(
            name="Policy pending ack", trigger_event="document_pending_acknowledgment", match_field="title", pattern="Policy"
        )
        rule.actions.append(PlatformEventAction(action_type="mark_problematic", config={}))
        session.add(rule)

        doc = await document_service.create_document(
            session, title="Security Policy", description=None, filename="policy.md",
            storage_key="phi/policy.md", mime_type="text/markdown", size_bytes=10, uploaded_by=None, tags=[],
        )
        await session.commit()

        await document_service.request_acknowledgment(session, doc, group_id=group.id, user_id=None)

        # Resolved to both group members, both still pending.
        assert await document_service.required_acknowledgment_user_ids(session, doc) == {reviewer_a.id, reviewer_b.id}
        assert await document_service.pending_acknowledgment_user_ids(session, doc) == {reviewer_a.id, reviewer_b.id}
        pending_for_a = await document_service.list_documents_pending_acknowledgment_for(session, reviewer_a.id)
        assert [d.id for d in pending_for_a] == [doc.id]

        # The matching rule fired -- logged against the document, not any
        # ticket, and the ticket-only action reports itself skipped rather
        # than silently doing nothing or raising.
        triggers = (
            await session.execute(select(PlatformEventTrigger).where(PlatformEventTrigger.document_id == doc.id))
        ).scalars().all()
        assert [t.rule_name for t in triggers] == ["Policy pending ack"]
        assert triggers[0].ticket_id is None
        assert "skipped" in triggers[0].summary

        # Reviewer A acknowledges -- clears their own pending status, B is
        # still pending, and A drops off their own Pending Actions list.
        await document_service.acknowledge_document(session, doc.id, reviewer_a.id)
        assert await document_service.pending_acknowledgment_user_ids(session, doc) == {reviewer_b.id}
        assert await document_service.list_documents_pending_acknowledgment_for(session, reviewer_a.id) == []
        assert [d.id for d in await document_service.list_documents_pending_acknowledgment_for(session, reviewer_b.id)] == [doc.id]

        # Re-requesting puts A back on the pending list without touching
        # their earlier (now stale) acknowledgment row.
        await document_service.request_acknowledgment(session, doc, group_id=group.id, user_id=None)
        assert await document_service.pending_acknowledgment_user_ids(session, doc) == {reviewer_a.id, reviewer_b.id}

        # Clearing the requirement entirely empties both.
        await document_service.clear_acknowledgment_requirement(session, doc)
        assert await document_service.required_acknowledgment_user_ids(session, doc) == set()
        assert await document_service.list_documents_pending_acknowledgment_for(session, reviewer_a.id) == []


async def test_deleting_asset_type_cascades_its_custom_fields():
    """AssetType.custom_fields needs passive_deletes=True -- without it,
    deleting an AssetType through the ORM makes SQLAlchemy's own unit-of-
    work null out asset_type_id on every CustomField row it loads to
    figure out what to do with them (its default handling of a nullable
    FK with no cascade= set), rather than leaving the DB's own ON DELETE
    CASCADE (the real FK constraint) to just delete them. The field then
    survives as an orphaned, tenant-wide field instead of being deleted,
    silently applying to every other asset type from then on -- confirmed
    live against a real Postgres before this was fixed, not simulated.

    Mirrors rain.modules.assets.router.delete_type exactly (`db.get`
    then `db.delete`, the collection never touched) rather than forcing
    a worse-case reproduction by pre-loading `custom_fields` first --
    that's a meaningfully different scenario (SQLAlchemy's handling of
    an already-resident collection isn't governed by passive_deletes the
    same way an unloaded one is), and isn't the path the app actually
    takes."""
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.db.tenant_models import AssetType, CustomField

    tenant = await provision_tenant(slug="chi", name="Chi Networks")

    async with tenant_session(tenant.schema_name) as session:
        asset_type = AssetType(key="widget", name="Widget")
        session.add(asset_type)
        await session.flush()
        field = CustomField(scope="asset", asset_type_id=asset_type.id, field_key="color", label="Color", field_type="text")
        session.add(field)
        await session.commit()
        field_id = field.id
        asset_type_id = asset_type.id

    # A fresh session/identity map, same as a fresh request -- `delete_
    # type` never has `custom_fields` loaded going in, since it never
    # queries CustomField at all.
    async with tenant_session(tenant.schema_name) as session:
        reloaded_type = await session.get(AssetType, asset_type_id)
        await session.delete(reloaded_type)
        await session.commit()

        # populate_existing=True: see test_document_tags_search_and_
        # calendar_link's own comment on why a plain get() would return
        # a stale identity-mapped object instead of the real DB state.
        assert await session.get(CustomField, field_id, populate_existing=True) is None


async def test_ticket_import_dedup_by_external_finding_key():
    """rain.modules.tickets.importer's opt-in "Dedup key" mapping end to
    end (migration 0050, Ticket.external_finding_key): a first import
    creates; a second import of the same key while the ticket is still
    open leaves it alone but refreshes its custom field values; closing
    the ticket and importing the same key again reopens it, flags it
    is_problematic (a regression is by definition no longer a one-off),
    and logs a comment -- and the DB's own UniqueConstraint is what a
    racing duplicate would actually be caught by, not just the
    service's own SELECT-before-insert check (see create_ticket's own
    comment on why the key is set at construction time, not after)."""
    from rain.db.tenant_models import CustomField, Ticket, TicketComment
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.modules.tickets import importer, service

    tenant = await provision_tenant(slug="psi", name="Psi Analytics")

    async with tenant_session(tenant.schema_name) as session:
        # "open"/"closed" don't need seeding here -- migration 0005 seeds
        # them (plus in_progress/resolved) for every tenant already.
        cvss_field = CustomField(scope="ticket", field_key="cvss", label="CVSS", field_type="number")
        session.add(cvss_field)
        await session.commit()

        row = {"Type": "vulnerability", "Title": "Outdated TLS", "Key": "nessus:10.0.0.5:443:51192", "CVSS": "4.3"}
        first = await importer.commit_import(
            session, rows=[row], mapping={"ticket_type": "Type", "title": "Title", "upsert_key": "Key", f"field_{cvss_field.id}": "CVSS"}, actor_id=None
        )
        assert (first.created, first.reopened, first.unchanged) == (1, 0, 0)

        tickets = await service.list_tickets(session, ticket_type="vulnerability")
        ticket = next(t for t in tickets if t.title == "Outdated TLS")
        assert ticket.external_finding_key == "nessus:10.0.0.5:443:51192"

        # Same key, still open, a different CVSS this time -- left alone
        # (no second ticket), but the field value refreshes.
        row["CVSS"] = "5.4"
        second = await importer.commit_import(
            session, rows=[row], mapping={"ticket_type": "Type", "title": "Title", "upsert_key": "Key", f"field_{cvss_field.id}": "CVSS"}, actor_id=None
        )
        assert (second.created, second.reopened, second.unchanged) == (0, 0, 1)
        reloaded = await service.get_ticket(session, ticket.id)
        assert reloaded is not None
        assert {fv.field_id: fv.value for fv in reloaded.field_values} == {cvss_field.id: 5.4}

        # Close it (simulating remediation), then the same finding
        # reappears in a later scan -- reopened, not duplicated.
        await service.update_status(session, ticket, "closed")
        third = await importer.commit_import(
            session, rows=[row], mapping={"ticket_type": "Type", "title": "Title", "upsert_key": "Key", f"field_{cvss_field.id}": "CVSS"}, actor_id=None
        )
        assert (third.created, third.reopened, third.unchanged) == (0, 1, 0)
        # populate_existing=True: ticket.id has already been loaded once
        # this session (its .comments collection eagerly populated as
        # empty at that point) -- without it, get_ticket's own
        # selectinload(Ticket.comments) hands back that stale, already-
        # in-the-identity-map collection instead of re-querying it, same
        # gotcha test_document_tags_search_and_calendar_link's own
        # comment on populate_existing already documents for a scalar
        # field, here for a relationship collection instead.
        reopened_ticket = (
            await session.execute(select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True))
        ).scalar_one()
        assert reopened_ticket.status == "open"
        assert reopened_ticket.is_problematic is True
        comment_bodies = (
            await session.execute(select(TicketComment.body).where(TicketComment.ticket_id == ticket.id))
        ).scalars().all()
        assert any("Reopened" in body for body in comment_bodies)

        # Still only ever the one ticket for this key across all three imports.
        assert len(await service.list_tickets(session, ticket_type="vulnerability")) == 1


_SAMPLE_NESSUS_XML = b"""<?xml version="1.0" ?>
<NessusClientData_v2>
<Report name="Sample Scan">
<ReportHost name="web01.internal">
<HostProperties>
<tag name="host-ip">10.0.0.5</tag>
</HostProperties>
<ReportItem port="443" protocol="tcp" severity="2" pluginID="51192" pluginName="SSL Certificate Cannot Be Trusted" pluginFamily="General">
<description>Cert chain is not trusted.</description>
<risk_factor>Medium</risk_factor>
<cvss_base_score>6.4</cvss_base_score>
</ReportItem>
<ReportItem port="0" protocol="tcp" severity="0" pluginID="19506" pluginName="Nessus Scan Information" pluginFamily="Settings">
<description>Scan details.</description>
</ReportItem>
</ReportHost>
</Report>
</NessusClientData_v2>
"""


async def test_nessus_import_parses_maps_and_dedups_end_to_end():
    """rain.modules.tickets.nessus_parser.parse_nessus_rows feeding
    rain.modules.tickets.importer.commit_import, the same pipeline
    Tickets > Import's "Nessus scan export (.nessus)" format uses --
    covers the Info-severity (0) finding being dropped before it's even
    a row, and that the parser's own column names (chosen to match this
    importer's target labels and nessus-finding-fields.json's field
    labels exactly) work as a real mapping dict, not just documentation.
    Re-running the same file is what actually proves the two features
    compose: the second pass matches by Dedup key and leaves the ticket
    alone rather than creating a duplicate."""
    from rain.db.tenant_models import CustomField, Ticket
    from rain.db.base import tenant_session
    from rain.db.provisioning import provision_tenant
    from rain.modules.tickets import importer, service
    from rain.modules.tickets.nessus_parser import parse_nessus_rows

    tenant = await provision_tenant(slug="omega", name="Omega Labs")

    async with tenant_session(tenant.schema_name) as session:
        plugin_field = CustomField(scope="ticket", field_key="nessus_plugin_id", label="Nessus plugin ID", field_type="text")
        session.add(plugin_field)
        await session.commit()

        rows = parse_nessus_rows(_SAMPLE_NESSUS_XML)
        assert len(rows) == 1  # the severity=0 row never became one

        mapping = {
            "ticket_type": "Type",
            "title": "Title",
            "description": "Description",
            "severity": "Severity",
            "upsert_key": "Dedup key (optional)",
            f"field_{plugin_field.id}": "Nessus plugin ID",
        }
        first = await importer.commit_import(session, rows=rows, mapping=mapping, actor_id=None)
        assert (first.created, first.reopened, first.unchanged, first.errors) == (1, 0, 0, [])

        tickets = await service.list_tickets(session, ticket_type="vulnerability")
        ticket = next(t for t in tickets if "SSL Certificate" in t.title)
        assert ticket.severity == "medium"
        assert ticket.external_finding_key == "nessus:10.0.0.5:443:tcp:51192"
        assert {fv.field_id: fv.value for fv in ticket.field_values} == {plugin_field.id: "51192"}

        # commit=False batching (create_ticket/add_watcher) didn't skip
        # committing entirely -- the ticket is really durable once
        # commit_import returns, not just flushed.
        assert await session.get(Ticket, ticket.id, populate_existing=True) is not None

        # Re-importing the identical file: same finding, same key,
        # left unchanged rather than duplicated.
        second = await importer.commit_import(session, rows=parse_nessus_rows(_SAMPLE_NESSUS_XML), mapping=mapping, actor_id=None)
        assert (second.created, second.unchanged) == (0, 1)
        assert len(await service.list_tickets(session, ticket_type="vulnerability")) == 1
