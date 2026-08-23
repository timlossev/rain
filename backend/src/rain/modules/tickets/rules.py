"""Event Promotion Policies: the one system that decides whether a
persisted syslog event becomes (or contributes to) a ticket. Evaluated by
the worker (rain.modules.tickets.listener) against every persisted event,
and by every other path that synthesizes one (rain.modules.calendar.sweep,
Document alert_on_change, WebhookConfig alert_on_failure, a completed
change approval's notify_syslog_on_approval) -- always through this
module's one entry point, evaluate_and_promote.

Used to be two separate systems evaluated independently: TicketRule
(single-event regex match, optionally folding a repeat onto an already-
open ticket via combine_by_title) and CorrelationRule (multi-event: a
"threshold" type counting N matches in a trailing window, or an
"ml_anomaly" online model). Unified into one table (TicketRule.
promotion_type: "single" | "repetition" | "ml_anomaly") and one module --
see TicketRule's own docstring and migration 0038 for why, and reused
against the rule editor's own "test against a sample" action (rules_test
in rain.modules.tickets.router)."""
from __future__ import annotations

import datetime as dt
import logging
import pickle
import re

from river import anomaly
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import Asset, SyslogEvent, Ticket, TicketRule, TicketRuleState
from rain.modules.tickets import service

logger = logging.getLogger("rain.rules")

GROUP_BY_FIELDS = ("none", "host", "program")
PROMOTION_TYPES = ("single", "repetition", "ml_anomaly")


def field_matches(match_field: str, pattern: str, event: SyslogEvent) -> bool:
    """The one matcher every rule concept in this module shares -- "does
    this event match this field/pattern" always means exactly the same
    thing everywhere, whether it's a single/repetition rule's own match
    or an ml_anomaly rule's base filter narrowing which events reach its
    model."""
    value = getattr(event, match_field, None)
    if not value:
        return False
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def rule_matches(rule: TicketRule, event: SyslogEvent) -> bool:
    return field_matches(rule.match_field, rule.pattern, event)


async def find_matching_rule(db: AsyncSession, event: SyslogEvent) -> TicketRule | None:
    """First active single/repetition rule (sort_order) matching this
    event -- used by evaluate_and_promote below, and directly by the rule
    editor's "test against a sample" action. Never considers ml_anomaly
    rules: those don't "match and produce a ticket" the way this
    single-match concept means, they score every event against a running
    model (see _evaluate_ml_one)."""
    result = await db.execute(
        select(TicketRule)
        .where(TicketRule.is_active.is_(True), TicketRule.promotion_type.in_(("single", "repetition")))
        .order_by(TicketRule.sort_order)
    )
    for rule in result.scalars():
        if rule_matches(rule, event):
            return rule
    return None


async def apply_rule(db: AsyncSession, rule: TicketRule, event: SyslogEvent) -> Ticket:
    """Turns one matching event into a ticket -- "single" always creates
    a fresh one; "repetition" folds a repeat occurrence (same computed
    title, still-open ticket of this rule's ticket_type) into that ticket
    instead (see service.combine_event_into_ticket)."""
    asset_id = None
    if rule.asset_match_field:
        value = getattr(event, rule.asset_match_field, None)
        if value:
            result = await db.execute(select(Asset).where(Asset.external_id == value))
            asset = result.scalar_one_or_none()
            asset_id = asset.id if asset else None

    title = rule.title_template.format(message=event.message or "", host=event.host or "", program=event.program or "")

    if rule.promotion_type == "repetition":
        existing = await service.find_open_ticket_by_title(db, rule.ticket_type, title)
        if existing is not None:
            await service.combine_event_into_ticket(db, existing, event)
            return existing

    return await service.create_ticket(
        db,
        ticket_type=rule.ticket_type,
        title=title,
        # The full event, not just message -- see build_event_description's
        # own docstring (same reasoning applies to a policy-triggered
        # promotion as a manual one).
        description=service.build_event_description(event),
        severity=rule.severity,
        asset_id=asset_id,
        source_event_id=event.id,
        source_rule_id=rule.id,
    )


async def evaluate_and_promote(db: AsyncSession, event: SyslogEvent) -> None:
    """The one entry point every syslog-event-producing path in the app
    calls, right after persisting+committing a new SyslogEvent. Loads
    every active TicketRule once, ordered by sort_order, and for each:

    - "single"/"repetition": the rule-producing kind -- first match wins
      (a message doesn't spawn two tickets), same as before "repetition"
      existed as its own promotion_type. Once one of these has produced
      or reused a ticket for this event, no later single/repetition rule
      gets a turn.
    - "ml_anomaly": never "consumes" the event the way the above do --
      every active ml_anomaly rule still scores it against its own
      running per-group model regardless of what a single/repetition
      rule above it did. This is the same "alongside, not instead of"
      property CorrelationRule used to have as a wholly separate system;
      unifying the table/evaluation loop doesn't change that shape, it
      just means both kinds are configured and evaluated in one place
      now instead of two.

    Never raises -- a broken rule must not take down event ingestion."""
    promoted = False
    result = await db.execute(select(TicketRule).where(TicketRule.is_active.is_(True)).order_by(TicketRule.sort_order))
    for rule in result.scalars():
        try:
            if rule.promotion_type == "ml_anomaly":
                await _evaluate_ml_one(db, rule, event)
            elif not promoted and rule_matches(rule, event):
                await apply_rule(db, rule, event)
                promoted = True
        except Exception:
            logger.exception("event promotion policy %s failed for event %s", rule.id, event.id)


# ------------------------------------------------------------ ml_anomaly ---


def _ml_features(event: SyslogEvent) -> dict[str, float]:
    """Deliberately small and numeric-only -- river.anomaly.HalfSpaceTrees
    scores a flat dict of numbers, not text, so this doesn't attempt any
    NLP over event.message itself. severity defaults to 6 ("info",
    syslog's own middle-of-the-road level) for an event with none set,
    rather than either extreme. message_length and hour_of_day are cheap
    proxies for "does this look like this source's normal traffic" --
    e.g. a message far longer/shorter than usual, or activity at a time
    of day this host/program is normally quiet -- without needing to
    understand the message's content."""
    received = event.received_at or dt.datetime.now(dt.timezone.utc)
    return {
        "severity": float(event.severity) if event.severity is not None else 6.0,
        "message_length": float(len(event.message or "")),
        "hour_of_day": float(received.hour),
    }


def _new_ml_model() -> anomaly.HalfSpaceTrees:
    return anomaly.HalfSpaceTrees()


def _load_ml_model(blob: bytes | None) -> anomaly.HalfSpaceTrees:
    if blob is None:
        return _new_ml_model()
    try:
        return pickle.loads(blob)
    except Exception:
        # Corrupt/incompatible state (e.g. a river version bump changing
        # the model's pickled shape) -- start over rather than take event
        # ingestion down over one rule's stale model.
        logger.exception("failed to deserialize ML anomaly model, starting a fresh one")
        return _new_ml_model()


async def _get_or_create_ml_state(db: AsyncSession, rule_id: int, group_key: str) -> TicketRuleState:
    # FOR UPDATE: this row is read, mutated in Python (score + train the
    # model), and written back -- not a single atomic SQL statement --
    # so two events for the same rule+group evaluated concurrently
    # (overlapping asyncio tasks, or the app and worker processes both
    # calling evaluate_and_promote at nearly the same time) need to
    # serialize on this row or one of them would silently lose the
    # other's model update on commit.
    result = await db.execute(
        select(TicketRuleState).where(TicketRuleState.rule_id == rule_id, TicketRuleState.group_key == group_key).with_for_update()
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = TicketRuleState(rule_id=rule_id, group_key=group_key, last_triggered_at=None, ml_event_count=0)
        db.add(state)
        await db.flush()
    return state


async def _evaluate_ml_one(db: AsyncSession, rule: TicketRule, event: SyslogEvent) -> None:
    if not field_matches(rule.match_field, rule.pattern, event):
        return
    if rule.group_by == "none":
        group_key = ""  # sentinel for "ungrouped" -- see TicketRuleState's docstring
    else:
        group_key = getattr(event, rule.group_by, None)
        if not group_key:
            return  # can't form a group key for this event, so it can't contribute to a grouped rule

    state = await _get_or_create_ml_state(db, rule.id, group_key)
    model = _load_ml_model(state.ml_model)

    x = _ml_features(event)
    score = model.score_one(x)
    model.learn_one(x)
    state.ml_model = pickle.dumps(model)
    state.ml_event_count += 1

    # Still building its baseline -- never fire until it's seen enough
    # events to know what "normal" looks like for this rule+group, or
    # every rule would flag its own cold start as one big anomaly.
    if state.ml_event_count < rule.ml_warmup_count:
        await db.commit()
        return

    if score < rule.ml_score_threshold:
        await db.commit()
        return

    now = dt.datetime.now(dt.timezone.utc)
    if state.last_triggered_at is not None and (now - state.last_triggered_at) < dt.timedelta(minutes=rule.window_minutes):
        await db.commit()  # still within the cooldown from the last trigger for this rule+group
        return

    await _fire_ml(db, rule, group_key, event, score)
    state.last_triggered_at = now
    await db.commit()


async def _fire_ml(db: AsyncSession, rule: TicketRule, group_key: str, event: SyslogEvent, score: float) -> None:
    asset_id = None
    if rule.asset_match_field:
        value = getattr(event, rule.asset_match_field, None)
        if value:
            result = await db.execute(select(Asset).where(Asset.external_id == value))
            asset = result.scalar_one_or_none()
            asset_id = asset.id if asset else None

    title = rule.title_template.format(
        count=1,
        window=rule.window_minutes,
        host=event.host or "",
        program=event.program or "",
        message=event.message or "",
        score=round(score, 3),
    )
    description_lines = [
        f"Anomaly score {score:.3f} (threshold {rule.ml_score_threshold}) on an online model trained over "
        f"{rule.ml_warmup_count}+ prior events" + (f" (grouped by {rule.group_by} = {group_key})" if group_key else ""),
        "",
        "Triggering event:",
        f"  {event.received_at.strftime('%Y-%m-%d %H:%M:%S') if event.received_at else ''}  "
        f"{event.host or '-'}  {event.program or '-'}  {(event.message or '')[:200]}",
    ]

    ticket = await service.create_ticket(
        db,
        ticket_type=rule.ticket_type,
        title=title,
        description="\n".join(description_lines),
        severity=rule.severity,
        asset_id=asset_id,
        source_rule_id=rule.id,
    )
    if event.promoted_ticket_id is None:
        event.promoted_ticket_id = ticket.id
