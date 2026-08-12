"""Query/mutation helpers for the calendar, kept thin and reusable between
the HTML router, the worker's syslog-event bridge sweep, and .ics export."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import CalendarEntry


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
