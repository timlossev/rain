"""rain.modules.calendar.recurrence -- occurrence math for CalendarEntry
presets. No DB involved: occurrences_in_range/is_due_on take a plain
object with start_date/recurrence/recurrence_end, so a SimpleNamespace
stands in for a real CalendarEntry exactly the way test_rules.py's _rule/
_event helpers stand in for TicketRule/SyslogEvent."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from rain.modules.calendar.recurrence import is_due_on, occurrences_in_range


def _entry(**kwargs):
    defaults = dict(start_date=dt.date(2026, 1, 1), recurrence="", recurrence_end=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _dates(entry, start, end):
    return occurrences_in_range(entry, start, end)


def test_non_recurring_entry_only_occurs_on_its_start_date():
    entry = _entry(start_date=dt.date(2026, 3, 5), recurrence="")
    assert _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 12, 31)) == [dt.date(2026, 3, 5)]
    assert _dates(entry, dt.date(2026, 3, 6), dt.date(2026, 12, 31)) == []


def test_entry_starting_after_range_end_never_occurs():
    entry = _entry(start_date=dt.date(2027, 1, 1), recurrence="monthly")
    assert _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 12, 31)) == []


def test_daily_recurrence_within_range():
    entry = _entry(start_date=dt.date(2026, 1, 1), recurrence="daily")
    dates = _dates(entry, dt.date(2026, 1, 5), dt.date(2026, 1, 8))
    assert dates == [dt.date(2026, 1, 5), dt.date(2026, 1, 6), dt.date(2026, 1, 7), dt.date(2026, 1, 8)]


def test_daily_recurrence_jumps_to_first_occurrence_without_counting_every_day():
    """An entry that started years ago still resolves correctly for a
    far-future range -- this is the whole point of _day_based_occurrences'
    division-based jump instead of counting from start_date one day at a
    time (see that function's own docstring)."""
    entry = _entry(start_date=dt.date(2000, 1, 1), recurrence="daily")
    dates = _dates(entry, dt.date(2026, 6, 1), dt.date(2026, 6, 2))
    assert dates == [dt.date(2026, 6, 1), dt.date(2026, 6, 2)]


def test_weekly_recurrence_steps_by_seven_days():
    entry = _entry(start_date=dt.date(2026, 1, 1), recurrence="weekly")  # a Thursday
    dates = _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    assert dates == [dt.date(2026, 1, 1), dt.date(2026, 1, 8), dt.date(2026, 1, 15), dt.date(2026, 1, 22), dt.date(2026, 1, 29)]


def test_monthly_recurrence_steps_by_one_month():
    entry = _entry(start_date=dt.date(2026, 1, 15), recurrence="monthly")
    dates = _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 4, 30))
    assert dates == [dt.date(2026, 1, 15), dt.date(2026, 2, 15), dt.date(2026, 3, 15), dt.date(2026, 4, 15)]


def test_quarterly_day_clamp_recovers_instead_of_ratcheting_down():
    """Jan 31 quarterly clamps to Apr 30 (April has 30 days), but the next
    occurrence is computed from the *original* Jan 31, not from the
    clamped Apr 30 -- so July, which does have 31 days, lands back on
    Jul 31 rather than permanently shifting to the 30th. This is the
    exact regression occurrences_in_range's own docstring/comment call
    out as previously broken and confirmed fixed."""
    entry = _entry(start_date=dt.date(2026, 1, 31), recurrence="quarterly")
    dates = _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert dates == [dt.date(2026, 1, 31), dt.date(2026, 4, 30), dt.date(2026, 7, 31), dt.date(2026, 10, 31)]


def test_annual_recurrence_on_leap_day_clamps_in_non_leap_years():
    entry = _entry(start_date=dt.date(2024, 2, 29), recurrence="annual")
    dates = _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert dates == [dt.date(2026, 2, 28)]


def test_recurrence_end_stops_future_occurrences():
    entry = _entry(start_date=dt.date(2026, 1, 1), recurrence="monthly", recurrence_end=dt.date(2026, 3, 1))
    dates = _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert dates == [dt.date(2026, 1, 1), dt.date(2026, 2, 1), dt.date(2026, 3, 1)]


def test_recurrence_end_applies_to_daily_recurrence_too():
    entry = _entry(start_date=dt.date(2026, 1, 1), recurrence="daily", recurrence_end=dt.date(2026, 1, 3))
    dates = _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    assert dates == [dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)]


def test_is_due_on_true_and_false():
    entry = _entry(start_date=dt.date(2026, 1, 31), recurrence="quarterly")
    assert is_due_on(entry, dt.date(2026, 4, 30)) is True
    assert is_due_on(entry, dt.date(2026, 4, 29)) is False


def test_range_inclusive_on_both_ends():
    entry = _entry(start_date=dt.date(2026, 1, 1), recurrence="daily")
    assert _dates(entry, dt.date(2026, 1, 1), dt.date(2026, 1, 1)) == [dt.date(2026, 1, 1)]
