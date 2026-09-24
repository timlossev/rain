"""rain.modules.webhooks.service -- the parts that don't need a real HTTP
call or a database session. _ticket_payload_text is the "user" message
call_chat_completion builds for a Chat Completions API webhook; duck-typed
stand-ins (not real Ticket/TicketFieldValue ORM rows) are enough since the
function only ever reads plain attributes off whatever it's given."""
from __future__ import annotations

from types import SimpleNamespace

from rain.modules.webhooks.service import _ticket_payload_text


def _field_value(label: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(field=SimpleNamespace(label=label), value=value)


def _ticket(**overrides) -> SimpleNamespace:
    base = dict(
        ticket_number="INC-000042",
        ticket_type="incident",
        title="db down",
        severity="high",
        status="open",
        asset=None,
        description="Primary database is unreachable from the app tier.",
        field_values=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_payload_text_includes_the_fixed_fields():
    text = _ticket_payload_text(_ticket())
    assert "Ticket: INC-000042" in text
    assert "Type: incident" in text
    assert "Title: db down" in text
    assert "Severity: high" in text
    assert "Status: open" in text
    assert "Primary database is unreachable from the app tier." in text


def test_payload_text_blank_description_says_none_not_blank():
    text = _ticket_payload_text(_ticket(description=None))
    assert "Description:\n(none)" in text


def test_payload_text_includes_linked_asset_when_present():
    text = _ticket_payload_text(_ticket(asset=SimpleNamespace(name="db-primary-01")))
    assert "Asset: db-primary-01" in text


def test_payload_text_omits_asset_line_when_unlinked():
    text = _ticket_payload_text(_ticket(asset=None))
    assert "Asset:" not in text


def test_payload_text_includes_custom_field_values_in_order():
    text = _ticket_payload_text(
        _ticket(field_values=[_field_value("Environment", "production"), _field_value("On-call", "jordan")])
    )
    assert "Custom fields:" in text
    lines = text.splitlines()
    env_idx = lines.index("- Environment: production")
    oncall_idx = lines.index("- On-call: jordan")
    assert oncall_idx == env_idx + 1


def test_payload_text_skips_custom_fields_section_when_none():
    text = _ticket_payload_text(_ticket(field_values=[]))
    assert "Custom fields:" not in text


def test_payload_text_skips_a_field_value_whose_field_was_deleted():
    """A CustomField row can be deleted out from under an old
    TicketFieldValue -- same defensive `fv.field is not None` filter
    other field-value renderers in this codebase already apply."""
    orphaned = SimpleNamespace(field=None, value="stale")
    text = _ticket_payload_text(_ticket(field_values=[orphaned, _field_value("Priority", "P1")]))
    assert "stale" not in text
    assert "- Priority: P1" in text
