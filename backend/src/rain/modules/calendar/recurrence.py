"""Occurrence computation for CalendarEntry.recurrence presets.

Occurrences are never materialized as rows -- always computed on the fly
from `start_date` plus a fixed month-step per preset, clamping the
day-of-month the way most calendar apps do (Jan 31 quarterly -> Apr 30,
not Feb 31 / an error). This keeps a recurring entry a single DB row no
matter how far out it's projected, and means changing an entry's
recurrence/start_date takes effect retroactively for any future date --
there's no stale materialized occurrence to clean up."""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Any

RECURRENCE_PRESETS: list[tuple[str | None, str]] = [
    ("", "Does not repeat"),
    ("quarterly", "Quarterly (every 3 months)"),
    ("biannual", "Every 6 months"),
    ("annual", "Annually"),
]
_MONTH_STEP = {"quarterly": 3, "biannual": 6, "annual": 12}

# The iteration cap below (400 steps) exists purely so a bad/missing
# recurrence_end can never spin forever; at the smallest step (3 months)
# that's still 100 years out, far past anything a real range query needs.
_MAX_STEPS = 400


def _add_months(d: dt.date, months: int) -> dt.date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def occurrences_in_range(entry: Any, range_start: dt.date, range_end: dt.date) -> list[dt.date]:
    """All occurrence dates of `entry` within [range_start, range_end], inclusive on both ends."""
    if entry.start_date > range_end:
        return []
    if entry.recurrence not in _MONTH_STEP:
        return [entry.start_date] if range_start <= entry.start_date <= range_end else []

    step = _MONTH_STEP[entry.recurrence]
    occurrences: list[dt.date] = []
    # Each occurrence is computed from the *original* start_date (n * step
    # months out), not by repeatedly stepping from the previous occurrence
    # -- otherwise a clamped day-of-month (e.g. Jan 31 -> Apr 30) ratchets
    # down permanently instead of recovering in a later month that could
    # fit the original day (Apr 30 -> Jul 30 instead of Jul 31, confirmed
    # by a real test before this fix).
    for n in range(_MAX_STEPS):
        current = _add_months(entry.start_date, step * n)
        if current > range_end:
            break
        if entry.recurrence_end and current > entry.recurrence_end:
            break
        if current >= range_start:
            occurrences.append(current)
    return occurrences


def is_due_on(entry: Any, day: dt.date) -> bool:
    """True if `entry` has an occurrence landing exactly on `day`."""
    return bool(occurrences_in_range(entry, day, day))
