# Screenshots

Captured against a local RAIN instance (`docker compose up`), with the
runtime branding, accent color, and font set from the setup wizard --
nothing here is mocked up.

## Records Authority (tickets)

| | |
|---|---|
| ![Ticket list](03-ticket-list.png) Ticket list, filtered and sorted, with quick-filter chips and a three-dot action menu per row. | ![Kanban board](05-kanban.png) The same tickets on a Kanban board, grouped by status or by assignee workload. |
| ![Ticket detail](04-ticket-detail.png) A single ticket: status stepper, quick actions, and the full activity feed. | ![Live events](06-events-live.png) The live syslog feed -- CEF/JSON/key=value auto-detected, filterable by severity. |

## Automation

| | |
|---|---|
| ![Event Promotion Policies](12-event-promotion-policies.png) Event Promotion Policies turn matching syslog events into tickets automatically. | ![Platform Response Rules](13-platform-response-rules.png) A rule's own actions as a flowchart -- icons connected by arrows in firing order, click a step to edit or remove it. |

### Correlation: repetition folding and ML anomaly detection

Repetition folding and ML anomaly detection walked through against real
syslog events end to end (policy config, then the resulting tickets) --
see [`../correlation-showcase.md`](../correlation-showcase.md) for the
full walkthrough.

| | |
|---|---|
| ![Event Promotion Policies list](correlation-01-policies.png) Event Promotion Policies list. | ![Repetition policy configuration](correlation-02-repetition-config.png) Repetition policy configuration. |
| ![Resulting Problematic ticket](correlation-04-repetition-ticket.png) Resulting Problematic ticket. | ![ML anomaly policy configuration](correlation-03-ml-config.png) ML anomaly policy configuration. |

![Resulting ML anomaly ticket](correlation-05-ml-ticket.png)

Resulting ML anomaly ticket.

### AI-assisted triage: Chat Completions API

A Platform Response Rule action that invokes a Chat Completions API
webhook (OpenAI, Gemini, ...) and posts the reply as a comment -- Level
0 triage of a security alert against a shared playbook document,
walked through end to end -- see
[`../ai-triage-showcase.md`](../ai-triage-showcase.md).

| | |
|---|---|
| ![The Security Operations Playbook, a plain-text Document](ai-triage-01-playbook-document.png) The Security Operations Playbook, a plain-text Document. | ![Webhook configuration: model, custom prompt, and the playbook picked as shared memory](ai-triage-02-webhook-config.png) Webhook configuration: model, custom prompt, and the playbook picked as shared memory. |
| ![The rule's action flow: one step, Invoke Chat Completions API](ai-triage-03-rule-flow.png) The rule's action flow: one step, Invoke Chat Completions API. | ![The resulting ticket: the AI's triage comment as the very first activity entry](ai-triage-04-ticket-result.png) The resulting ticket: the AI's triage comment as the very first activity entry. |

## Assets, documents, calendar

| | |
|---|---|
| ![Asset list](07-asset-list.png) The asset registry, with no-code custom fields per type. | ![Document list](08-document-list.png) The document repository, with tags and status flags. |
| ![Document detail](09-document-detail.png) A document's own page -- Basics, Ownership, Acknowledgment, and Visibility as their own tabs, plus contents, links, and calendar. | ![Calendar](10-calendar.png) The per-tenant calendar, with recurring entries and a syslog bridge. |

### OSCAL SSP: importing FedRAMP High and exporting a control register

Importing the real FedRAMP High baseline as a Security Control asset
register and exporting it as OSCAL, walked through end to end -- see
[`../oscal-ssp-showcase.md`](../oscal-ssp-showcase.md).

| | |
|---|---|
| ![Assets Import screen with the High baseline CSV selected](oscal-01-import-high-baseline.png) Assets Import screen with the High baseline CSV selected. | ![Column mapping, fully auto-suggested](oscal-02-import-mapping.png) Column mapping, fully auto-suggested. |
| ![Import result](oscal-03-import-result.png) Import result. | ![AC-2(a), unanswered](oscal-04-control-before.png) AC-2(a), unanswered. |
| ![AC-2(a), answered](oscal-05-control-after.png) AC-2(a), answered. | ![The Security Control register, filtered](oscal-06-register-list.png) The Security Control register, filtered. |

![Export screen, all Security Control columns selected](oscal-07-export-screen.png)

Export screen, all Security Control columns selected.

### FedRAMP CR26: Significant Change Notifications

FedRAMP's 2026 Consolidated Rules (CR26) explained through a real
Significant Change Notification on a Change ticket -- see
[`../fedramp-cr26-showcase.md`](../fedramp-cr26-showcase.md).

![A Change ticket carrying its own SCN fields, pending CAB approval](scn-01-change-ticket.png)

A Change ticket carrying its own SCN fields, pending CAB approval.

### CR26 coverage: SBOM, crypto modules, ConMon

Three more CR26 review areas -- SBOM/software inventory, cryptographic
module tracking, and Continuous Monitoring submissions -- against real
data, see [`../cr26-coverage-showcase.md`](../cr26-coverage-showcase.md).

| | |
|---|---|
| ![A Software Component: OpenSSL, with version, source, license, and scope](cr26-01-sbom-component.png) A Software Component: OpenSSL, with version, source, license, and scope. | ![An Encryption Key / Certificate row, with FIPS validation status, certificate number, and module name filled in](cr26-02-crypto-module.png) An Encryption Key / Certificate row, with FIPS validation status, certificate number, and module name filled in. |

![A ConMon Submission for 2026-09, with scan/POA&M summaries, finding counts, and who it was shared with](cr26-03-conmon-submission.png)

A ConMon Submission for 2026-09, with scan/POA&M summaries, finding counts, and who it was shared with.

### Drift detection: a document webhook, a calendar sweep, and a policy

A document webhook, a calendar sweep, and an Event Promotion Policy
composed into unattended infrastructure drift detection -- a real
out-of-band change caught and ticketed automatically -- see
[`../drift-detection-showcase.md`](../drift-detection-showcase.md).

| | |
|---|---|
| ![The baseline inventory, typed in as a plain-text Document](drift-01-baseline-document.png) The baseline inventory, typed in as a plain-text Document. | ![Auto-update tab: webhook picked, syslog alert on change turned on](drift-02-auto-update-config.png) Auto-update tab: webhook picked, syslog alert on change turned on. |
| ![Calendar entry: weekly recurrence, the inventory document related, auto-refresh on](drift-03-calendar-entry.png) Calendar entry: weekly recurrence, the inventory document related, auto-refresh on. | ![Event Promotion Policy: match program against this document's own number](drift-04-policy.png) Event Promotion Policy: match program against this document's own number. |

![The resulting ticket: real diff, real alert, no human involved yet](drift-05-ticket.png)

The resulting ticket: real diff, real alert, no human involved yet.

## Search, portal, admin

| | |
|---|---|
| ![Search results](11-search-results.png) Global full-text search across tickets, documents, and assets. | ![Client portal](15-client-portal.png) The public client portal -- file a request with no account, with an at-a-glance status strip once signed in. |
| ![Admin branding](14-admin-branding.png) Runtime branding and the public-portal settings, no redeploy needed. | ![Home](02-home.png) The landing page, driven by a flagged document. |

![Sign in](01-login.png)

Sign in -- local, LDAP, and SAML accounts all use this same form.
