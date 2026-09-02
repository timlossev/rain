"""rain.modules.tickets.platform_events -- the pure matching logic that
decides whether a Platform Response Rule fires for a given ticket.
Mirrors test_rules.py's pattern for the sibling syslog-promotion module:
a SimpleNamespace stands in for PlatformEventRule/Ticket, so this covers
_rule_matches without a DB (the rest of the module -- _evaluate_and_fire,
_fire_rule, _run_action -- is DB- and network-bound and covered instead
by the platform-event-rule integration test in test_integration.py)."""
from __future__ import annotations

from types import SimpleNamespace

from rain.modules.tickets.platform_events import ACTION_TYPES, TRIGGER_EVENTS, _action_label, _rule_matches


def _rule(**kwargs):
    defaults = dict(match_field="title", pattern="outage")
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _ticket(**kwargs):
    defaults = dict(title=None, description=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_rule_matches_on_title():
    rule = _rule(pattern="major outage")
    assert _rule_matches(rule, _ticket(title="major outage in us-east"))


def test_rule_does_not_match_different_text():
    rule = _rule(pattern="major outage")
    assert not _rule_matches(rule, _ticket(title="minor blip"))


def test_rule_matches_is_case_sensitive_by_default():
    rule = _rule(pattern="Outage")
    assert not _rule_matches(rule, _ticket(title="outage detected"))


def test_rule_does_not_match_when_field_empty():
    rule = _rule(match_field="description", pattern=".+")
    assert not _rule_matches(rule, _ticket(description=None))
    assert not _rule_matches(rule, _ticket(description=""))


def test_rule_matches_on_description_field():
    rule = _rule(match_field="description", pattern=r"^CVE-\d{4}-\d+")
    assert _rule_matches(rule, _ticket(description="CVE-2026-6357 affects the base image"))
    assert not _rule_matches(rule, _ticket(description="see CVE-2026-6357 below"))


def test_invalid_regex_does_not_raise():
    rule = _rule(pattern="[unclosed")
    assert _rule_matches(rule, _ticket(title="anything")) is False


def test_action_label_falls_back_to_raw_type_for_unknown_action():
    assert _action_label("notify_slack") == "Notify Slack"
    assert _action_label("mystery_action") == "mystery_action"


def test_trigger_events_and_action_types_are_well_formed():
    """Both are rendered directly into admin/platform_event_detail.html's
    dropdowns -- a duplicate or malformed key there would silently offer
    two identical options or break the config lookup in _run_action."""
    trigger_keys = [key for key, _label in TRIGGER_EVENTS]
    assert len(trigger_keys) == len(set(trigger_keys))
    action_keys = [key for key, _label in ACTION_TYPES]
    assert len(action_keys) == len(set(action_keys))
    assert "mark_problematic" in action_keys
    assert "incident_created" in trigger_keys
    assert "document_pending_acknowledgment" in trigger_keys


def test_rule_matches_against_a_document_the_same_way_as_a_ticket():
    """_rule_matches is pure attribute access (getattr(record, match_field)
    then a regex search) -- it never actually cared whether `record` was a
    Ticket or a Document, so a document-shaped SimpleNamespace (doc_number
    instead of ticket_number, everything else the same title/description
    pair) matches identically. Covers the document_pending_acknowledgment
    trigger path this module added alongside the ticket ones above."""
    rule = _rule(match_field="title", pattern="policy")
    document = SimpleNamespace(doc_number="DOC-000042", title="Security policy v3", description=None)
    assert _rule_matches(rule, document)
    assert not _rule_matches(rule, SimpleNamespace(doc_number="DOC-000043", title="Runbook", description=None))
