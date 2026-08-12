"""Daily sweep bridging due calendar-entry occurrences into synthetic
syslog events, so the *existing* rule engine (TicketRule -> Event
Policies, then Platform Events on the resulting ticket) reacts to them
exactly as it would a real syslog-ng-delivered event -- no separate
calendar-specific rule system needed. Mirrors the tail end of
rain.modules.tickets.listener.handle_raw_line (resolve rule, promote to
ticket), but skips tenant resolution (already iterating one tenant schema
at a time here) and the live-viewer publish (these aren't real network
events, and the live viewer is for watching traffic arrive)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import select

from rain.db.base import control_session, tenant_session
from rain.db.control_models import Tenant
from rain.db.tenant_models import SyslogEvent
from rain.modules.calendar import recurrence
from rain.modules.calendar import service as calendar_service
from rain.modules.tickets import rules

logger = logging.getLogger("rain.calendar_sweep")

# Hourly is plenty of headroom for a once-a-day-granularity feature; the
# last_fired_date guard makes re-running within the same day a no-op.
SWEEP_INTERVAL_SECONDS = 3600


async def run_calendar_sweep() -> None:
    today = dt.date.today()
    async with control_session() as control_db:
        result = await control_db.execute(select(Tenant.schema_name).where(Tenant.is_active.is_(True)))
        schemas = list(result.scalars())

    for schema_name in schemas:
        try:
            async with tenant_session(schema_name) as db:
                entries = await calendar_service.list_entries(db, active_only=True)
                for entry in entries:
                    if not entry.emit_syslog_event or entry.last_fired_date == today:
                        continue
                    if not recurrence.is_due_on(entry, today):
                        continue

                    event = SyslogEvent(
                        host="calendar",
                        program=entry.event_program or entry.title,
                        facility=None,
                        severity=6,  # info
                        message=entry.description or entry.title,
                        raw=f"calendar entry #{entry.id}: {entry.title}",
                    )
                    db.add(event)
                    await db.commit()

                    matched_rule = await rules.find_matching_rule(db, event)
                    if matched_rule is not None:
                        await rules.apply_rule(db, matched_rule, event)

                    await calendar_service.mark_fired(db, entry, today)
        except Exception:
            logger.exception("calendar sweep failed for schema %s", schema_name)


async def calendar_sweep_loop() -> None:
    while True:
        await run_calendar_sweep()
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
