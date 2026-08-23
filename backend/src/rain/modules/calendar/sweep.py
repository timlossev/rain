"""Daily sweep acting on due calendar-entry occurrences. Two independent
things can happen per occurrence, each opt-in on the entry itself:

- `emit_syslog_event`: bridges into a synthetic syslog event, so the
  *existing* rule engine (TicketRule -> Event Policies, then Platform
  Events on the resulting ticket) reacts to it exactly as it would a real
  syslog-ng-delivered event -- no separate calendar-specific rule system
  needed. Mirrors the tail end of rain.modules.tickets.listener.
  handle_raw_line (resolve rule, promote to ticket), but skips tenant
  resolution (already iterating one tenant schema at a time here) and the
  live-viewer publish (these aren't real network events).
- `policy_ref` of type "refresh_document": the concrete realization of
  the policy_ref hook described on CalendarEntry -- calls
  rain.modules.documents.service.refresh_from_webhook for the referenced
  document, the same "call its webhook, diff, save, optionally alert"
  logic the document's own "Refresh from webhook" button uses.

Both are independent (an entry can do either, both, or neither), but
share the same due-occurrence check and last_fired_date dedup marker."""
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
from rain.modules.documents import service as document_service
from rain.modules.tickets import rules

logger = logging.getLogger("rain.calendar_sweep")

# Hourly is plenty of headroom for a once-a-day-granularity feature; the
# last_fired_date guard makes re-running within the same day a no-op.
SWEEP_INTERVAL_SECONDS = 3600


def _refresh_document_id(entry) -> int | None:
    policy = entry.policy_ref or {}
    if policy.get("type") == "refresh_document":
        return policy.get("document_id")
    return None


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
                    document_id = _refresh_document_id(entry)
                    if entry.last_fired_date == today or (not entry.emit_syslog_event and document_id is None):
                        continue
                    if not recurrence.is_due_on(entry, today):
                        continue

                    if entry.emit_syslog_event:
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

                        await rules.evaluate_and_promote(db, event)

                    if document_id is not None:
                        doc = await document_service.get_document(db, document_id)
                        if doc is None:
                            logger.warning(
                                "calendar entry #%s refers to a deleted document #%s", entry.id, document_id
                            )
                        else:
                            outcome = await document_service.refresh_from_webhook(db, doc)
                            if not outcome.ok:
                                logger.warning(
                                    "calendar entry #%s: document %s refresh failed: %s",
                                    entry.id,
                                    doc.doc_number,
                                    outcome.error,
                                )

                    await calendar_service.mark_fired(db, entry, today)
        except Exception:
            logger.exception("calendar sweep failed for schema %s", schema_name)


async def calendar_sweep_loop() -> None:
    while True:
        await run_calendar_sweep()
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
