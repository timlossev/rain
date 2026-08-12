from __future__ import annotations

from types import SimpleNamespace

from rain.modules.tickets.rules import rule_matches


def _rule(**kwargs):
    defaults = dict(match_field="message", pattern="failed", is_active=True)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _event(**kwargs):
    defaults = dict(message=None, host=None, program=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_rule_matches_on_message():
    rule = _rule(pattern="failed password")
    assert rule_matches(rule, _event(message="failed password for invalid user"))


def test_rule_matches_is_case_sensitive_by_default():
    rule = _rule(pattern="Failed")
    assert not rule_matches(rule, _event(message="failed password"))


def test_rule_does_not_match_when_field_empty():
    rule = _rule(match_field="host", pattern=".+")
    assert not rule_matches(rule, _event(host=None))


def test_rule_matches_on_host():
    rule = _rule(match_field="host", pattern=r"^web-\d+$")
    assert rule_matches(rule, _event(host="web-01"))
    assert not rule_matches(rule, _event(host="db-01"))


def test_invalid_regex_does_not_raise():
    rule = _rule(pattern="[unclosed")
    assert rule_matches(rule, _event(message="anything")) is False
