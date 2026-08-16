"""Two correlation strategies for Event Promotion Policies, both evaluated
once per newly-persisted syslog event (rain.modules.tickets.listener),
not on a timer, since the only thing that can push either kind of rule
over its line is the event that was just persisted:

- "threshold": "N events matching a base pattern within T minutes,
  optionally per host/program." Deliberately does the counting in
  Python, not a `~`-based COUNT(*) query in Postgres -- the base filter
  needs to mean *exactly* the same thing here as it does for TicketRule's
  single-event matching (same field_matches() helper, Python's `re`
  engine) -- Postgres's `~` operator is POSIX ERE, not Python re, close
  enough to cause silent, hard-to-notice discrepancies between "does
  this new event match" and "how many recent events match" if two
  different regex engines were involved. The candidate set pulled from
  the DB is already bounded by the time window (and further by the
  group-by equality filter when grouped), so filtering that in Python
  costs nothing worth worrying about.
- "ml_anomaly": scores each matching event against a per rule+group_key
  online model (river.anomaly.HalfSpaceTrees) and fires once its
  anomaly score clears the rule's threshold. See _evaluate_ml_one and
  CorrelationRule/CorrelationRuleState's docstrings for the model
  lifecycle, feature set, and why persisting/unpickling its state here
  is safe.
"""
from __future__ import annotations

import datetime as dt
import logging
import pickle

from river import anomaly
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from rain.db.tenant_models import Asset, CorrelationRule, CorrelationRuleState, SyslogEvent
from rain.modules.tickets import service
from rain.modules.tickets.rules import field_matches

logger = logging.getLogger("rain.correlation")

GROUP_BY_FIELDS = ("none", "host", "program")
RULE_TYPES = ("threshold", "ml_anomaly")


async def evaluate_correlation_rules(db: AsyncSession, event: SyslogEvent) -> None:
    """Never raises -- a broken rule must not take down event ingestion."""
    result = await db.execute(
        select(CorrelationRule).where(CorrelationRule.is_active.is_(True)).order_by(CorrelationRule.sort_order)
    )
    for rule in result.scalars():
        try:
            if rule.rule_type not in RULE_TYPES:
                continue
            # Same base filter for both rule types -- an ml_anomaly rule
            # left with its default ".*" pattern scores every event;
            # narrowing it (e.g. to "auth failure") scopes the model to
            # just that slice of traffic, same idea as threshold's own
            # pattern field.
            if not field_matches(rule.match_field, rule.pattern, event):
                continue
            if rule.group_by == "none":
                group_key = ""  # sentinel for "ungrouped" -- see CorrelationRuleState's docstring
            else:
                group_key = getattr(event, rule.group_by, None)
                if not group_key:
                    continue  # can't form a group key for this event, so it can't contribute to a grouped rule
            if rule.rule_type == "threshold":
                await _evaluate_one(db, rule, group_key)
            else:
                await _evaluate_ml_one(db, rule, group_key, event)
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
    # last_triggered_at is nullable at the column level (an ml_anomaly
    # group's state row can exist without ever having fired -- see
    # CorrelationRuleState's docstring), but a "threshold" row is only
    # ever created by _fire below with a real timestamp, so the `is not
    # None` here is defensive, not expected to ever matter in practice.
    if state is not None and state.last_triggered_at is not None and (now - state.last_triggered_at) < dt.timedelta(
        minutes=rule.window_minutes
    ):
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


async def _get_or_create_ml_state(db: AsyncSession, rule_id: int, group_key: str) -> CorrelationRuleState:
    # FOR UPDATE: this row is read, mutated in Python (score + train the
    # model), and written back -- not a single atomic SQL statement the
    # way _fire's timestamp bump is -- so two events for the same
    # rule+group evaluated concurrently (overlapping asyncio tasks, or
    # the app and worker processes both calling evaluate_correlation_rules
    # at nearly the same time) need to serialize on this row or one of
    # them would silently lose the other's model update on commit.
    result = await db.execute(
        select(CorrelationRuleState)
        .where(CorrelationRuleState.rule_id == rule_id, CorrelationRuleState.group_key == group_key)
        .with_for_update()
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = CorrelationRuleState(rule_id=rule_id, group_key=group_key, last_triggered_at=None, ml_event_count=0)
        db.add(state)
        await db.flush()
    return state


async def _evaluate_ml_one(db: AsyncSession, rule: CorrelationRule, group_key: str, event: SyslogEvent) -> None:
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
    if state.last_triggered_at is not None and (now - state.last_triggered_at) < dt.timedelta(
        minutes=rule.window_minutes
    ):
        await db.commit()  # still within the cooldown from the last trigger for this rule+group
        return

    await _fire_ml(db, rule, group_key, event, score)
    state.last_triggered_at = now
    await db.commit()


async def _fire_ml(db: AsyncSession, rule: CorrelationRule, group_key: str, event: SyslogEvent, score: float) -> None:
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
        source_correlation_rule_id=rule.id,
    )
    if event.promoted_ticket_id is None:
        event.promoted_ticket_id = ticket.id
