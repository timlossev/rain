"""Query/mutation helpers for the calendar, kept thin and reusable between
the HTML router, the worker's syslog-event bridge sweep, and .ics export."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import CalendarEntry, Ticket
from rain.modules.calendar.recurrence import is_due_on


def calendar_entries_stmt(*, active_only: bool = False):
    stmt = select(CalendarEntry).order_by(CalendarEntry.start_date)
    if active_only:
        stmt = stmt.where(CalendarEntry.is_active.is_(True))
    return stmt


async def list_entries(db: AsyncSession, *, active_only: bool = False) -> list[CalendarEntry]:
    result = await db.execute(calendar_entries_stmt(active_only=active_only))
    return list(result.scalars())


async def get_entry(db: AsyncSession, entry_id: int) -> CalendarEntry | None:
    return await db.get(CalendarEntry, entry_id)


async def list_entries_for_document(db: AsyncSession, document_id: int) -> list[CalendarEntry]:
    """Backs a document's own Calendar tab -- every entry (active or not,
    unlike the month grid) linked to it via CalendarEntry.document_id,
    regardless of whether it also auto-refreshes that document via
    policy_ref (see CalendarEntry's own docstring)."""
    stmt = select(CalendarEntry).where(CalendarEntry.document_id == document_id).order_by(CalendarEntry.start_date)
    result = await db.execute(stmt)
    return list(result.scalars())


async def document_ids_with_calendar_entries(db: AsyncSession) -> set[int]:
    """Every Document.id with at least one linked CalendarEntry -- backs
    the Documents list's calendar-icon flag (rain.modules.documents.
    router.list_documents), one cheap distinct query up front instead of
    list_entries_for_document called once per row."""
    stmt = select(CalendarEntry.document_id).where(CalendarEntry.document_id.is_not(None)).distinct()
    result = await db.execute(stmt)
    return set(result.scalars())


async def create_entry(db: AsyncSession, **fields: Any) -> CalendarEntry:
    entry = CalendarEntry(**fields)
    db.add(entry)
    await db.commit()
    return entry


async def update_entry(db: AsyncSession, entry: CalendarEntry, **fields: Any) -> None:
    for key, value in fields.items():
        setattr(entry, key, value)
    await db.commit()


async def delete_entry(db: AsyncSession, entry: CalendarEntry) -> None:
    await db.delete(entry)
    await db.commit()


async def mark_fired(db: AsyncSession, entry: CalendarEntry, on: dt.date) -> None:
    entry.last_fired_date = on
    await db.commit()


async def list_entries_due_today(db: AsyncSession) -> list[CalendarEntry]:
    """Active entries with an occurrence landing on today. Reuses the
    same occurrence math (rain.modules.calendar.recurrence.is_due_on)
    the month-grid view computes each cell from, rather than a second
    definition of what "due" means. See list_due_today below for what
    actually backs the client portal's "Today's events" listing --
    CalendarEntry occurrences alone under-counted what the full
    calendar page shows for the same day."""
    entries = await list_entries(db, active_only=True)
    today = dt.datetime.now(dt.timezone.utc).date()
    return [e for e in entries if is_due_on(e, today)]


async def list_due_today(db: AsyncSession) -> list[CalendarEntry | Ticket]:
    """Everything "for today" the way the full /calendar month grid
    defines it -- CalendarEntry occurrences (list_entries_due_today)
    *and* change tickets whose [start_date, end_date] window covers
    today (list_changes_in_range), the same two sources rain.modules.
    calendar.router's own grid-building combines into by_date/
    changes_by_date. Backs the client portal's "Today's events" widget,
    which used to call list_entries_due_today alone -- a tenant with,
    say, one CalendarEntry and two changes scheduled for today would
    see all three on the full calendar page but only the one
    CalendarEntry here, which read as "only one item" despite having
    multiple entries for the day.

    Both `Ticket` and `CalendarEntry` have their own `.title`, so a
    caller that only ever read that attribute works unchanged against
    the merged list; portal/report.html additionally checks for
    `.ticket_number` (Jinja's `is defined`, safe against the
    AttributeError a CalendarEntry raises for that name) to prefix a
    change's ticket number the same way the month grid's own chip
    does."""
    today = dt.datetime.now(dt.timezone.utc).date()
    entries = await list_entries_due_today(db)
    changes = await list_changes_in_range(db, today, today)
    return [*entries, *changes]


async def list_changes_in_range(db: AsyncSession, start: dt.date, end: dt.date) -> list[Ticket]:
    """Change tickets whose [start_date, end_date] window overlaps [start,
    end] -- shown on the calendar month grid alongside CalendarEntry
    occurrences. Both dates must be set (a change with only one of the two
    filled in isn't placeable on a grid) and neither is null-safe against
    the other in the overlap check below, so both are required in the
    WHERE clause. start/end are grid day bounds (dates); start_date/
    end_date are now timestamptz (a change's window can start/end
    mid-day), so they're widened to whole-day bounds here for the
    overlap comparison rather than handing asyncpg a bare date for a
    timestamptz parameter."""
    start_dt = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(end, dt.time.max, tzinfo=dt.timezone.utc)
    stmt = select(Ticket).where(
        Ticket.ticket_type == "change",
        Ticket.start_date.is_not(None),
        Ticket.end_date.is_not(None),
        Ticket.start_date <= end_dt,
        Ticket.end_date >= start_dt,
    )
    result = await db.execute(stmt)
    return list(result.scalars())
