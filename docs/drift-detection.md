# Infrastructure Drift Detection (SI-7 / CM-8(3))

Not a dedicated feature. Three existing capabilities, combined: a
webhook-populated document, a recurring calendar refresh, and
(optionally) an Event Promotion Policy. No separate module, no extra
code -- see [`docs/architecture.md`](architecture.md#document-repository)
for how the three pieces are wired together internally.

## Controls this supports

- **SI-7** (Software, Firmware, and Information Integrity) and
  **CM-8(3)** (Automated Unauthorized Component Detection): a scheduled
  discovery run against live infrastructure, diffed against the last
  snapshot, alerting automatically when they disagree.
- Pairs with CM-2 (baseline -- the initial snapshot) and CM-3 (approval
  trail -- change tickets) to cover "every change was approved, and
  nothing else happened." See
  [`docs/itsm-controls-mapping.md`](itsm-controls-mapping.md) for the
  full control mapping.

## Setup

1. Run a discovery tool against the environment on a schedule --
   Terraform plus [Terracognita](https://github.com/cycloid-community-catalog/terracognita)
   or equivalent -- and publish its output somewhere reachable over
   HTTP. RAIN does not run this step.
2. **Documents > New document**, "Populate from webhook" tab. Point
   Webhook at that endpoint and check "Emit syslog alert on change."
   Every refresh diffs the new response against what's stored and only
   alerts when they differ.
3. **Calendar > New entry** on that document: pick a recurrence, check
   "Also auto-refresh from its webhook," set Related document to it.
   The sweep runs hourly and only re-fetches on the day(s) the
   recurrence says to.
4. Optional, to turn a detected diff into a ticket: **Tickets > Event
   Promotion Policies**, a policy matching field "program" against the
   document's own number (`DOC-xxxxxx`, unique per document, so the
   policy only fires for this one monitor). The diff text is in the
   resulting event and can be pulled into the ticket description.

## Starter template

[`docs/compliance-templates/cloud-environment-register.rain`](compliance-templates/cloud-environment-register.rain)
seeds a Cloud Environment asset type, for tracking which account or
environment each monitor covers.

## What this is not

RAIN does not run Terraform, Terracognita, or any discovery tool, and
does not interpret the diff. It stores whatever text the pipeline
produces and alerts on change -- nothing more.
