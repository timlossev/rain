"""Threshold correlation for Event Policies: "N events matching a base
pattern within T minutes, optionally per host/program" -- evaluated once
per newly-persisted syslog event (rain.modules.tickets.listener), not on
a timer, since the only thing that can push a threshold rule over its
line is the event that was just persisted.

Deliberately does the counting in Python, not a `~`-based COUNT(*) query
in Postgres: the base filter needs to mean *exactly* the same thing here
as it does for TicketRule's single-event matching (same field_matches()
helper, Python's `re` engine) -- Postgres's `~` operator is POSIX ERE,
not Python re, close enough to cause silent, hard-to-notice discrepancies
between "does this new event match" and "how many recent events match"
if two different regex engines were involved. The candidate set pulled
from the DB is already bounded by the time window (and further by the
group-by equality filter when grouped), so filtering that in Python
costs nothing worth worrying about.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import Asset, CorrelationRule, CorrelationRuleState, SyslogEvent
from rain.modules.tickets import service
from rain.modules.tickets.rules import field_matches

logger = logging.getLogger("rain.correlation")

GROUP_BY_FIELDS = ("none", "host", "program")


async def evaluate_correlation_rules(db: AsyncSession, event: SyslogEvent) -> None:
    """Never raises -- a broken rule must not take down event ingestion."""
    result = await db.execute(
        select(CorrelationRule).where(CorrelationRule.is_active.is_(True)).order_by(CorrelationRule.sort_order)
    )
    for rule in result.scalars():
        try:
            if rule.rule_type != "threshold":
                continue  # only kind implemented so far -- see the model docstring
            if not field_matches(rule.match_field, rule.pattern, event):
                continue
            if rule.group_by == "none":
                group_key = ""  # sentinel for "ungrouped" -- see CorrelationRuleState's docstring
            else:
                group_key = getattr(event, rule.group_by, None)
                if not group_key:
                    continue  # can't form a group key for this event, so it can't contribute to a grouped rule
            await _evaluate_one(db, rule, group_key)
        except Exception:
            logger.exception("correlation rule %s failed for event %s", rule.id, event.id)


async def _evaluate_one(db: AsyncSession, rule: CorrelationRule, group_key: str) -> None:
    now = dt.datetime.now(dt.timezone.utc)

    state = (
        await db.execute(
            select(CorrelationRuleState).where(
                CorrelationRuleState.rule_id == rule.id, CorrelationRuleState.group_key == group_key
            )
        )
    ).scalar_one_or_none()
    if state is not None and (now - state.last_triggered_at) < dt.timedelta(minutes=rule.window_minutes):
        return  # still within the cooldown from the last trigger for this rule+group

    cutoff = now - dt.timedelta(minutes=rule.window_minutes)
    candidates_stmt = select(SyslogEvent).where(SyslogEvent.received_at >= cutoff)
    if rule.group_by != "none":
        candidates_stmt = candidates_stmt.where(getattr(SyslogEvent, rule.group_by) == group_key)
    candidates = list((await db.execute(candidates_stmt)).scalars())

    matching = [e for e in candidates if field_matches(rule.match_field, rule.pattern, e)]
    if len(matching) < rule.threshold_count:
        return

    await _fire(db, rule, group_key, matching, now)


async def _fire(
    db: AsyncSession, rule: CorrelationRule, group_key: str, matching: list[SyslogEvent], now: dt.datetime
) -> None:
    latest = matching[-1]

    asset_id = None
    if rule.asset_match_field:
        value = getattr(latest, rule.asset_match_field, None)
        if value:
            result = await db.execute(select(Asset).where(Asset.external_id == value))
            asset = result.scalar_one_or_none()
            asset_id = asset.id if asset else None

    title = rule.title_template.format(
        count=len(matching),
        window=rule.window_minutes,
        host=latest.host or "",
        program=latest.program or "",
        message=latest.message or "",
    )
    description_lines = [
        f'{len(matching)} events matched "{rule.pattern}" within {rule.window_minutes} minute(s)'
        + (f" (grouped by {rule.group_by} = {group_key})" if group_key else ""),
        "",
        "Most recent matching events:",
    ]
    for e in matching[-10:]:
        when = e.received_at.strftime("%Y-%m-%d %H:%M:%S") if e.received_at else ""
        description_lines.append(f"  {when}  {e.host or '-'}  {e.program or '-'}  {(e.message or '')[:200]}")

    ticket = await service.create_ticket(
        db,
        ticket_type=rule.ticket_type,
        title=title,
        description="\n".join(description_lines),
        severity=rule.severity,
        asset_id=asset_id,
        source_correlation_rule_id=rule.id,
    )

    # Link every contributing event to the resulting ticket, same as a
    # single-event TicketRule promotion does for its one event -- lets a
    # user browsing Events see which ones got grouped into this ticket.
    for e in matching:
        if e.promoted_ticket_id is None:
            e.promoted_ticket_id = ticket.id

    # Upsert (not select-then-insert/update) so two events arriving close
    # enough together to be processed as overlapping asyncio tasks can't
    # both decide the state row doesn't exist yet and both try to insert
    # it, tripping the (rule_id, group_key) unique constraint.
    stmt = (
        pg_insert(CorrelationRuleState)
        .values(rule_id=rule.id, group_key=group_key, last_triggered_at=now)
        .on_conflict_do_update(
            index_elements=[CorrelationRuleState.rule_id, CorrelationRuleState.group_key],
            set_={"last_triggered_at": now},
        )
    )
    await db.execute(stmt)
    await db.commit()
