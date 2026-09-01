"""rain.modules.tickets.rootcause -- the one pure helper in this module.
summarize_chronic/find_similar_closed_tickets/analyze all need a real
AsyncSession (tsvector/@@ can't be faked with a stub), so those are
covered by the root-cause integration test in test_integration.py
instead; _format_span is a plain timedelta -> str formatter and doesn't
need a DB at all."""
from __future__ import annotations

import datetime as dt

from rain.modules.tickets.rootcause import _format_span


def test_format_span_minutes_only():
    assert _format_span(dt.timedelta(minutes=5)) == "5m"


def test_format_span_rounds_down_to_at_least_one_minute():
    assert _format_span(dt.timedelta(seconds=10)) == "1m"


def test_format_span_hours_and_minutes():
    assert _format_span(dt.timedelta(hours=2, minutes=15)) == "2h15m"


def test_format_span_exact_hours_omits_zero_minutes():
    assert _format_span(dt.timedelta(hours=3)) == "3h"


def test_format_span_days_and_hours():
    assert _format_span(dt.timedelta(days=2, hours=5)) == "2d5h"


def test_format_span_exact_days_omits_zero_hours():
    assert _format_span(dt.timedelta(days=4)) == "4d"
