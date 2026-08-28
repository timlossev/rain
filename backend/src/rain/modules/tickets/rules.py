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
import math
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

# Every river.anomaly detector that shares evaluate_and_promote's
# score_one(x)/learn_one(x) call shape (no supervised target `y`) --
# confirmed against the installed river==0.21.2: the other three
# detectors in that module (GaussianScorer, StandardAbsoluteDeviation,
# PredictiveAnomalyDetection) all require a `y` this app has no ground
# truth to supply, so they aren't real options here, not just omitted
# for brevity. Keyed by what TicketRule.ml_algorithm stores; each value
# is (display label, plain-language explanation shown on the rule form,
# zero-arg factory). New model each time a rule/group needs a fresh one
# (never reused across group keys -- every group gets its own instance).
ML_ALGORITHMS: dict[str, tuple[str, str, "type[anomaly.base.AnomalyDetector]"]] = {
    "half_space_trees": (
        "Half-Space Trees",
        "Tree-ensemble that isolates points via random splits. Fast, low-memory, a solid general-purpose default - best at point anomalies: a single event whose values are just far outside the norm.",
        anomaly.HalfSpaceTrees,
    ),
    "local_outlier_factor": (
        "Local Outlier Factor",
        "Compares a point's local neighborhood density to its neighbors'. Better at contextual anomalies - values that aren't extreme in isolation but are unusual for that particular time or place - at the cost of keeping a window of recent points, pricier per event than Half-Space Trees.",
        anomaly.LocalOutlierFactor,
    ),
    "one_class_svm": (
        "One-Class SVM",
        "Learns a smooth boundary around \"normal.\" Works best when normal behavior is fairly stable and anomalies are moderate deviations rather than wild spikes; more sensitive to feature scaling than the other two.",
        anomaly.OneClassSVM,
    ),
}
DEFAULT_ML_ALGORITHM = "half_space_trees"


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


def _default_change_window() -> tuple[dt.datetime, dt.datetime]:
    """A rule-produced change ticket's implementation window, when the
    rule doesn't ask for anything more specific than "file it now": start
    now, 24h turnaround -- the same reasonable default a human would
    otherwise have to type in by hand on the manual "New ticket" form."""
    start = dt.datetime.now(dt.timezone.utc)
    return start, start + dt.timedelta(hours=24)


async def _maybe_attach_change_approval(db: AsyncSession, rule: TicketRule, ticket: Ticket) -> None:
    """A rule producing a change ticket can name which approval flow to
    attach (rule.approval_flow_id) -- the same ChangeApproval machinery
    the manual "New ticket" form and Service Catalog use
    (service.start_approval), just picked ahead of time on the rule
    instead of asked for at submission. No-op for anything but a change,
    or a rule with no flow configured (files an unprotected change, same
    as leaving that field blank on the manual form)."""
    if rule.ticket_type != "change" or rule.approval_flow_id is None:
        return
    await service.start_approval(db, ticket, rule.approval_flow_id)


async def apply_rule(db: AsyncSession, rule: TicketRule, event: SyslogEvent) -> Ticket:
    """Turns one matching event into a ticket -- "single" always creates
    a fresh one; "repetition" folds a repeat occurrence (same computed
    title, still-open ticket of this rule's ticket_type) into that ticket
    instead (see service.combine_event_into_ticket). A "repetition" rule
    with ml_sidecar_enabled also runs this event through the same
    anomaly-scoring _evaluate_ml_one uses for a standalone ml_anomaly
    rule, on whichever ticket this call ends up returning -- see
    _annotate_if_anomalous. A newly created (never a folded-into) change
    ticket also gets its implementation window defaulted and its
    approval flow attached -- see _default_change_window/
    _maybe_attach_change_approval."""
    asset_id = None
    if rule.asset_match_field:
        value = getattr(event, rule.asset_match_field, None)
        if value:
            result = await db.execute(select(Asset).where(Asset.external_id == value))
            asset = result.scalar_one_or_none()
            asset_id = asset.id if asset else None

    title = rule.title_template.format(message=event.message or "", host=event.host or "", program=event.program or "")

    ticket: Ticket | None = None
    if rule.promotion_type == "repetition":
        ticket = await service.find_open_ticket_by_title(db, rule.ticket_type, title)
        if ticket is not None:
            await service.combine_event_into_ticket(db, ticket, event)

    if ticket is None:
        start_date, end_date = _default_change_window() if rule.ticket_type == "change" else (None, None)
        ticket = await service.create_ticket(
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
            start_date=start_date,
            end_date=end_date,
        )
        await _maybe_attach_change_approval(db, rule, ticket)

    if rule.promotion_type == "repetition" and rule.ml_sidecar_enabled:
        await _annotate_if_anomalous(db, rule, event, ticket)

    return ticket


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
      now instead of two. A "repetition" rule with ml_sidecar_enabled
      runs this same scoring too (see apply_rule), just inline as part
      of its own turn rather than needing a second, standalone
      ml_anomaly rule with a duplicated pattern.

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


def _new_ml_model(algorithm: str):
    _, _, factory = ML_ALGORITHMS.get(algorithm, ML_ALGORITHMS[DEFAULT_ML_ALGORITHM])
    return factory()


def _load_ml_model(blob: bytes | None, algorithm: str):
    if blob is None:
        return _new_ml_model(algorithm)
    try:
        return pickle.loads(blob)
    except Exception:
        # Corrupt/incompatible state (e.g. a river version bump changing
        # the model's pickled shape) -- start over rather than take event
        # ingestion down over one rule's stale model.
        logger.exception("failed to deserialize ML anomaly model, starting a fresh one")
        return _new_ml_model(algorithm)


def _feature_zscores(stats: dict, features: dict[str, float]) -> dict[str, float]:
    """z-score of each feature value against its OWN running mean/stdev
    for this rule+group -- how many standard deviations off "typical"
    this event's value is, computed BEFORE this event updates those
    stats (so "typical" reflects prior history, not including the very
    event being scored). Skips a feature with fewer than 2 prior samples
    (no variance to compare against yet) or zero historical variance
    (every prior value identical -- would divide by zero)."""
    zscores = {}
    for key, value in features.items():
        feat_stats = stats.get(key)
        if not feat_stats or feat_stats["n"] < 2:
            continue
        variance = feat_stats["m2"] / (feat_stats["n"] - 1)
        if variance <= 0:
            continue
        zscores[key] = (value - feat_stats["mean"]) / math.sqrt(variance)
    return zscores


def _update_feature_stats(stats: dict, features: dict[str, float]) -> dict:
    """Welford's online algorithm, one feature at a time -- (n, mean, m2)
    per feature is all that's kept, no stored history, safe to run on
    every scored event regardless of how many there have been so far."""
    updated = dict(stats)
    for key, value in features.items():
        feat_stats = updated.get(key, {"n": 0, "mean": 0.0, "m2": 0.0})
        n = feat_stats["n"] + 1
        delta = value - feat_stats["mean"]
        mean = feat_stats["mean"] + delta / n
        m2 = feat_stats["m2"] + delta * (value - mean)
        updated[key] = {"n": n, "mean": mean, "m2": m2}
    return updated


_FEATURE_LABELS = {"severity": "severity", "message_length": "message length", "hour_of_day": "hour of day"}


def _describe_deviation(zscores: dict[str, float], features: dict[str, float]) -> str | None:
    """Plain-language "why this looked unusual," for the single
    most-deviated feature -- not causal reasoning (nothing here
    understands *why* severity or message length changed), just which
    of the three numeric signals the model saw was furthest from this
    rule+group's own history, and by how much. None if there isn't
    enough history yet to say anything (see _feature_zscores)."""
    if not zscores:
        return None
    key, z = max(zscores.items(), key=lambda kv: abs(kv[1]))
    return (
        f"Most unusual signal: {_FEATURE_LABELS.get(key, key)} ({features[key]:.0f}), "
        f"{abs(z):.1f} standard deviations from this group's typical value."
    )


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


async def _score_for_anomaly(db: AsyncSession, rule: TicketRule, event: SyslogEvent) -> tuple[bool, float, str | None, str] | None:
    """The scoring/statekeeping core shared by _evaluate_ml_one (a
    standalone "ml_anomaly" rule, fires a new ticket) and
    _annotate_if_anomalous (a "repetition" rule's ml_sidecar_enabled,
    fires a comment on the ticket repetition already touched) -- same
    model, same warm-up/threshold/cooldown gating either way, only what
    happens on a fire differs, which is the caller's job, not this
    function's.

    None if this event doesn't reach this rule at all (match_field/
    pattern, or no group_key to score against). Otherwise
    (fired, score, deviation, group_key): `fired` is whether warm-up,
    threshold, and cooldown all cleared just now -- on a fire,
    state.last_triggered_at is updated but NOT committed here, since the
    caller still has its own fire-action (create a ticket, or add a
    comment to one) to perform on this same session first; both of
    those already commit on their own, which is what actually persists
    every mutation this function made. The non-fired paths commit
    directly since there's nothing further for the caller to do."""
    if not field_matches(rule.match_field, rule.pattern, event):
        return None
    if rule.group_by == "none":
        group_key = ""  # sentinel for "ungrouped" -- see TicketRuleState's docstring
    else:
        group_key = getattr(event, rule.group_by, None)
        if not group_key:
            return None  # can't form a group key for this event, so it can't contribute to a grouped rule

    state = await _get_or_create_ml_state(db, rule.id, group_key)
    model = _load_ml_model(state.ml_model, rule.ml_algorithm)

    x = _ml_features(event)
    score = model.score_one(x)
    # zscores computed against the stats as they stood BEFORE this event
    # -- deliberately before _update_feature_stats below folds this
    # event's own values in, so "typical" means "typical so far," not
    # "typical including the possible anomaly itself."
    zscores = _feature_zscores(state.ml_feature_stats or {}, x)
    model.learn_one(x)
    state.ml_model = pickle.dumps(model)
    state.ml_feature_stats = _update_feature_stats(state.ml_feature_stats or {}, x)
    state.ml_event_count += 1

    # Still building its baseline -- never fire until it's seen enough
    # events to know what "normal" looks like for this rule+group, or
    # every rule would flag its own cold start as one big anomaly.
    if state.ml_event_count < rule.ml_warmup_count:
        await db.commit()
        return False, score, None, group_key

    if score < rule.ml_score_threshold:
        await db.commit()
        return False, score, None, group_key

    now = dt.datetime.now(dt.timezone.utc)
    if state.last_triggered_at is not None and (now - state.last_triggered_at) < dt.timedelta(minutes=rule.window_minutes):
        await db.commit()  # still within the cooldown from the last trigger for this rule+group
        return False, score, None, group_key

    state.last_triggered_at = now
    return True, score, _describe_deviation(zscores, x), group_key


async def _evaluate_ml_one(db: AsyncSession, rule: TicketRule, event: SyslogEvent) -> None:
    result = await _score_for_anomaly(db, rule, event)
    if result is None:
        return
    fired, score, deviation, group_key = result
    if fired:
        await _fire_ml(db, rule, group_key, event, score, deviation)
        await db.commit()


async def _annotate_if_anomalous(db: AsyncSession, rule: TicketRule, event: SyslogEvent, ticket: Ticket) -> None:
    """A "repetition" rule's ml_sidecar_enabled: same scoring as a
    standalone ml_anomaly rule, against this rule's own ml_algorithm/
    group_by/window_minutes/ml_score_threshold/ml_warmup_count -- but on
    a fire, adds a comment to `ticket` (whichever one apply_rule's own
    fold-or-create just touched) instead of creating a second, separate
    ticket. Runs on every matching event, not just repeats, so the
    model builds its baseline from the very first occurrence onward."""
    result = await _score_for_anomaly(db, rule, event)
    if result is None:
        return
    fired, score, deviation, group_key = result
    if not fired:
        return
    algorithm_label = ML_ALGORITHMS.get(rule.ml_algorithm, ML_ALGORITHMS[DEFAULT_ML_ALGORITHM])[0]
    lines = [
        f"Statistically unusual occurrence (score {score:.3f}, threshold {rule.ml_score_threshold}, {algorithm_label} model)"
        + (f", grouped by {rule.group_by} = {group_key}" if group_key else "")
        + "."
    ]
    if deviation:
        lines.append(deviation)
    await service.add_comment(db, ticket.id, author_user_id=None, body="\n".join(lines))


async def _fire_ml(
    db: AsyncSession, rule: TicketRule, group_key: str, event: SyslogEvent, score: float, deviation: str | None
) -> None:
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
    algorithm_label = ML_ALGORITHMS.get(rule.ml_algorithm, ML_ALGORITHMS[DEFAULT_ML_ALGORITHM])[0]
    description_lines = [
        f"Anomaly score {score:.3f} (threshold {rule.ml_score_threshold}) on a {algorithm_label} model trained "
        f"over {rule.ml_warmup_count}+ prior events" + (f" (grouped by {rule.group_by} = {group_key})" if group_key else ""),
    ]
    if deviation:
        description_lines.append(deviation)
    description_lines += [
        "",
        "Triggering event:",
        f"  {event.received_at.strftime('%Y-%m-%d %H:%M:%S') if event.received_at else ''}  "
        f"{event.host or '-'}  {event.program or '-'}  {(event.message or '')[:200]}",
    ]

    start_date, end_date = _default_change_window() if rule.ticket_type == "change" else (None, None)
    ticket = await service.create_ticket(
        db,
        ticket_type=rule.ticket_type,
        title=title,
        description="\n".join(description_lines),
        severity=rule.severity,
        asset_id=asset_id,
        source_rule_id=rule.id,
        start_date=start_date,
        end_date=end_date,
    )
    await _maybe_attach_change_approval(db, rule, ticket)
    if event.promoted_ticket_id is None:
        event.promoted_ticket_id = ticket.id
