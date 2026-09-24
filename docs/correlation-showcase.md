# Event correlation showcase

RAIN's **Event Promotion Policies** (Records Authority > Event Promotion
Policies) decide whether an incoming syslog event becomes a ticket, gets
folded into one that's already open, or just sits in the event feed
untouched. There are three promotion types, and they aren't mutually
exclusive -- a policy is one of "Single event" or "Repetition" (first
match wins, so an event never spawns two tickets that way), plus any
number of "ML anomaly" policies can score the same event independently
on top of that. This page walks through two of them against real events
sent to a local instance -- nothing here is mocked up, screenshots
included. See [`docs/architecture.md`](architecture.md)'s Ticketing
section for the underlying implementation
(`rain.modules.tickets.rules`).

## 1. Repetition: folding repeats into one ticket

A **Repetition** policy computes a title from the matching event (here,
`Repeated failed SSH logins on {host}`). The first matching event opens
a new ticket as usual. Every later event that computes the *same* title
against a still-open ticket of that type gets folded into it instead of
opening a duplicate -- added as a "Repeat occurrence" comment, with the
ticket flagged **Problematic** so it's visible at a glance on any ticket
list without reading every comment.

![Event Promotion Policies list](screenshots/correlation-01-policies.png)

The policy list shows all three promotion types side by side: a
pre-existing "Single event" policy, this "Repetition" policy, and the
"ML anomaly" policy from part 2 below (already showing **LIVE**, having
cleared its warm-up).

![Repetition policy configuration](screenshots/correlation-02-repetition-config.png)

Configuration: match on `message` against the regex `authentication
failure`, promotion type Repetition. "Also flag statistically unusual
occurrences" is checked -- it's on by default for a new policy, and
left on here -- which runs an independent anomaly sidecar over this
same repeated-event group (severity, message length, time of day) so
that a stream of otherwise-routine repeats can still surface the one
that's genuinely unusual. Its own training status table shows 4 of the
250 events it needs to build a baseline.

Four synthetic `sudo` PAM auth-failure events were sent over the
syslog listener (`nc localhost 5514`, RFC 3164 framing), all from host
`web-prod-03`:

```
<86>Sep 23 09:51:54 web-prod-03 sudo[4821]: pam_unix(sudo:auth): authentication failure; ...
<86>Sep 23 09:51:55 web-prod-03 sudo[4833]: pam_unix(sudo:auth): authentication failure; ...
<86>Sep 23 09:51:56 web-prod-03 sudo[4841]: pam_unix(sudo:auth): authentication failure; ...
<86>Sep 23 09:51:57 web-prod-03 sudo[4855]: pam_unix(sudo:auth): authentication failure; ...
```

The first opened `INC-000002`; the next three each computed the same
title against that still-open ticket and folded in instead of opening
their own:

![Resulting Problematic ticket](screenshots/correlation-04-repetition-ticket.png)

`HIGH PRIORITY` / `PROBLEMATIC` / `INCIDENT`, "Reported by: Event
Promotion Policy: Repeated SSH login failures," and three "Repeat
occurrence -- last occurred on ..." comments in the activity feed below
(one per folded-in event, each carrying that event's own parsed KV
fields and raw line) -- one ticket instead of four, with the full
history preserved rather than discarded.

## 2. ML anomaly: scoring events against a learned baseline

An **ML anomaly** policy never competes with Single/Repetition for an
event -- every active ML policy scores every event that matches its own
pattern, independently, and fires once its score clears its threshold.
No threshold *count* to tune by hand: it learns what's typical (event
severity, message length, time of day) from the events it's already
seen, scores each new one against that baseline (0-1, higher = more
unusual), and stays quiet until it's seen its configured warm-up count
-- so a brand-new policy doesn't flag its own cold start as one big
anomaly.

![ML anomaly policy configuration](screenshots/correlation-03-ml-config.png)

Configuration: match on `message` against `ALLOW OUT` (a firewall
allow-rule log line), grouped by `host` (a separate model per host
rather than one shared model), Local Outlier Factor as the algorithm
(better than the default Half-Space Trees at this kind of small-sample
demo -- see the field's own hint text for the actual trade-off:
contextual anomalies vs. raw speed/memory), a warm-up of 10 events, and
the default 0.7 anomaly-score threshold.

Ten routine firewall lines were sent first, all from host `fw-edge-01`,
constant severity and near-constant length:

```
<134>Sep 23 ... fw-edge-01 pf[300]: ALLOW OUT tcp 10.0.1.15:51000 -> 93.184.216.34:443
<134>Sep 23 ... fw-edge-01 pf[300]: ALLOW OUT tcp 10.0.1.15:51001 -> 93.184.216.34:443
... (8 more, same shape)
```

Then one distinctly different line -- higher severity, a much longer
message, and content that reads as suspicious on its own:

```
<130>Sep 23 ... fw-edge-01 pf[300]: ALLOW OUT tcp 10.0.1.15:59999 -> 185.220.101.7:4444 SUSPICIOUS-LARGE-TRANSFER bytes=48302119 flagged-by-threat-intel=true tor-exit-node=true country=RU asn=AS12297
```

The ten baseline events all scored 0.0 against the model as it was
still being built (and wouldn't have fired regardless -- the warm-up
count hadn't been reached yet). The eleventh, scored against a baseline
now established from those ten, cleared the threshold and fired:

![Resulting ML anomaly ticket](screenshots/correlation-05-ml-ticket.png)

The ticket's own description states exactly what fired and why:
"Anomaly score 1.000 (threshold 0.7) on a Local Outlier Factor model
trained over 10+ prior events (grouped by host = fw-edge-01)," followed
by the triggering event's full text -- an assessor (or an on-call
engineer at 3am) doesn't have to trust the score, they can see the
input it was computed from.

## 3. Layering policies to cut ticket volume

Both parts above show one policy firing once. In practice a tenant runs
several policies together, ordered by `sort_order`, and that ordering is
what turns a noisy event feed into a small, actionable ticket queue
instead of a 1:1 mirror of it. A SOC watching 500 raw syslog events a
day is a realistic starting point -- failed-login noise, routine
firewall allow lines, health-check chatter, the occasional real
incident -- and it's not unusual for a handful of well-placed policies
to take that down to 10-20% as tickets: 50-100 records instead of 500,
each one worth a human looking at.

**How the reduction actually happens**, mechanically:

- **Repetition folds the bulk of it.** The four-line brute-force example
  above is the pattern at small scale -- in a real feed, a noisy source
  might produce dozens or hundreds of matching lines a day. A single
  Repetition policy with a title template like `Repeated failed SSH
  logins on {host}` turns all of them, per host, into one ticket with N
  "Repeat occurrence" comments, not N tickets. This is where most of the
  volume goes: a handful of known-noisy patterns, each covered by one
  policy, each collapsing many events into one still-open ticket instead
  of a fresh one every time.
- **ML anomaly stays quiet by design.** An `ml_anomaly` policy (or a
  Repetition policy's own `ml_sidecar_enabled`) doesn't produce a ticket
  per event it sees -- it scores every matching event against a learned
  baseline and only fires once the score clears `ml_score_threshold`,
  and only after `ml_warmup_count` events have taught it what "normal"
  looks like for that `group_by` key. In part 2 above, ten baseline
  events scored 0.0 and produced nothing; only the eleventh, genuinely
  different one fired. At scale that ratio holds: routine traffic trains
  the model and produces no tickets, only the outliers do.
- **Single-event policies are the deliberate exception.** A "Single
  event" policy (the third promotion type, not walked through above)
  tickets every match, no folding -- appropriate for patterns rare
  enough, or serious enough, that each occurrence deserves its own
  record regardless of whether an identical one already exists. Used
  narrowly (a specific alert signature, not a broad catch-all), it adds
  a small, intentional number of tickets on top of the two mechanisms
  above rather than undoing their reduction.
- **Everything unmatched costs nothing.** An event that doesn't match
  any active policy's `match_field`/`pattern` just sits in the live
  Events feed -- visible, searchable, never promoted. Routine
  health-check and cron noise a team has no policy for isn't "10% of a
  ticket," it's zero.

**The controls that shape this, per policy:**

| Control | Applies to | What it does |
|---|---|---|
| `match_field` / `pattern` | all | Which events this policy even looks at -- the regex a real event either matches or doesn't. |
| `sort_order` | single, repetition | Evaluation order for the first-match-wins pass -- see "sandwiching" below. |
| `title_template` | single, repetition | What makes two events "the same" for repetition folding -- two events computing the same title against a still-open ticket of that type fold together; different titles never do, however similar the raw text. |
| `ml_sidecar_enabled` | repetition | Runs the same anomaly scoring below on a repetition rule's own events, so a stream of otherwise-routine repeats can still surface the one that's statistically unusual, with no second policy needed. |
| `group_by` (none / host / program) | ml_anomaly | A separate learned model per group-key value, so "unusual for `fw-edge-01`" and "unusual for `fw-edge-02`" aren't judged against the same baseline. |
| `ml_algorithm` | ml_anomaly | Half-Space Trees (fast, low-memory, best at point anomalies -- the default), Local Outlier Factor (density-based, better at contextual anomalies, meaningful sooner on small samples), or One-Class SVM (boundary-based, best when "normal" is stable and anomalies are moderate deviations rather than spikes). |
| `ml_warmup_count` | ml_anomaly | Events a group's model must see before it's allowed to fire at all -- keeps a brand-new policy's own cold start from reading as one big anomaly. |
| `ml_score_threshold` | ml_anomaly | The 0-1 score (higher = more unusual) a scored event has to clear to fire. |
| `window_minutes` | ml_anomaly | Re-arm cooldown after a fire, per group -- not a scoring window, a "don't fire again on this group for N minutes" throttle. |

**Sandwiching**: because single/repetition policies evaluate in
`sort_order` and the first match wins, a tenant can stack narrow,
specific policies ahead of broad ones -- a handful of Repetition
policies for the loudest known-noisy patterns first (each one folding
its own flood into a single ticket), a Single-event catch-all last with
a broad pattern (or none at all) to still ticket anything genuinely new
that slipped past every narrower policy above it. ML anomaly policies
don't need a slot in that ordering at all -- every active one scores
every matching event independently, alongside whatever the
single/repetition pass decided, so a tenant can layer "fold the known
noise, catch anything new, and separately flag anything statistically
weird" without those three concerns competing for the same event.

**Routing onward**: none of the above is the end of the pipeline. A
policy promoting or folding an event only decides whether and how a
*ticket* gets created -- what happens next is a second, independent
layer: **Platform Response Rules** (same Records Authority section,
`rain.modules.tickets.platform_events`) react to that ticket's lifecycle
(created, closed, a change fully approved) regardless of whether a
policy promoted it automatically or a human opened it by hand, and
every active matching rule fires, not just the first. Its actions cover
notification (Slack, email), integration (a generic webhook, or the
newer **Invoke Chat Completions API** action -- see
[`ai-triage-showcase.md`](ai-triage-showcase.md) for that one walked
through end to end), and ticket handling (attach a document or asset,
mark problematic, analyze root cause, add a watcher). So the full
picture for one event is: Event Promotion Policies decide *if and how*
it becomes a ticket (new, folded, or flagged anomalous), then Platform
Response Rules decide *what happens to that ticket* -- who's notified,
what gets attached, whether an AI triage comment lands before anyone
opens it.

## Reproducing this

1. Admin > Syslog Listener: add a routing rule (`host` matches `.*`,
   regex) pointing at your tenant, if one isn't already configured.
2. Records Authority > Event Promotion Policies > New policy: build the
   two policies above (or your own pattern/promotion-type combination).
3. Feed it real or synthetic RFC 3164 lines on the syslog listener port
   (`5514` by default, TCP or UDP, newline-delimited):
   `printf '<86>...\n' | nc localhost 5514`.
4. Watch Records Authority > Events (live) as they arrive, or jump
   straight to the resulting ticket once a policy fires.
