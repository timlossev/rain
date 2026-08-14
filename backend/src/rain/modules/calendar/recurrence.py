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
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly (every 3 months)"),
    ("biannual", "Every 6 months"),
    ("annual", "Annually"),
]
_MONTH_STEP = {"monthly": 1, "quarterly": 3, "biannual": 6, "annual": 12}
_DAY_STEP = {"daily": 1, "weekly": 7}

# The iteration cap below exists purely so a bad/missing recurrence_end
# can never spin forever; at the smallest month-step (1, "monthly") that's
# still ~166 years out, far past anything a real range query needs.
# Day-based presets (daily/weekly) don't use this cap at all -- see
# _day_based_occurrences, which jumps straight to the first occurrence
# on or after range_start instead of counting up from the entry's
# start_date, so an old daily/weekly entry queried far in its future
# isn't paying (or capped by) an iteration count proportional to its age.
_MAX_STEPS = 2000


def _add_months(d: dt.date, months: int) -> dt.date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def _day_based_occurrences(entry: Any, range_start: dt.date, range_end: dt.date, step_days: int) -> list[dt.date]:
    """Daily/weekly occurrences -- a fixed number of days, so (unlike the
    month-based presets below) the first occurrence on or after
    range_start can be jumped to directly via division instead of
    counting up from start_date one step at a time. That matters here
    specifically: an entry started years ago, recurring daily, still
    only costs a handful of iterations to render this month's grid,
    rather than one iteration per day since it started."""
    start = entry.start_date
    if start >= range_start:
        first_n = 0
    else:
        first_n = -(-(range_start - start).days // step_days)  # ceil division

    occurrences: list[dt.date] = []
    n = first_n
    while True:
        current = start + dt.timedelta(days=step_days * n)
        if current > range_end:
            break
        if entry.recurrence_end and current > entry.recurrence_end:
            break
        occurrences.append(current)
        n += 1
    return occurrences


def occurrences_in_range(entry: Any, range_start: dt.date, range_end: dt.date) -> list[dt.date]:
    """All occurrence dates of `entry` within [range_start, range_end], inclusive on both ends."""
    if entry.start_date > range_end:
        return []
    if entry.recurrence in _DAY_STEP:
        return _day_based_occurrences(entry, range_start, range_end, _DAY_STEP[entry.recurrence])
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
