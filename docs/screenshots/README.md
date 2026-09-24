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

For repetition folding and ML anomaly detection walked through against
real syslog events end to end (policy config, then the resulting
tickets), see
[`../correlation-showcase.md`](../correlation-showcase.md). For a
Platform Response Rule action that invokes a Chat Completions API
webhook (OpenAI, Gemini, ...) and posts the reply as a comment -- Level
0 triage of a security alert against a shared playbook document, walked
through end to end -- see
[`../ai-triage-showcase.md`](../ai-triage-showcase.md).

## Assets, documents, calendar

| | |
|---|---|
| ![Asset list](07-asset-list.png) The asset registry, with no-code custom fields per type. | ![Document list](08-document-list.png) The document repository, with tags and status flags. |
| ![Document detail](09-document-detail.png) A document's own page -- Basics, Ownership, Acknowledgment, and Visibility as their own tabs, plus contents, links, and calendar. | ![Calendar](10-calendar.png) The per-tenant calendar, with recurring entries and a syslog bridge. |

For importing the real FedRAMP High baseline as a Security Control
asset register and exporting it as OSCAL, walked through end to end,
see [`../oscal-ssp-showcase.md`](../oscal-ssp-showcase.md). For
FedRAMP's 2026 Consolidated Rules (CR26) explained through a real
Significant Change Notification on a Change ticket, see
[`../fedramp-cr26-showcase.md`](../fedramp-cr26-showcase.md).

## Search, portal, admin

| | |
|---|---|
| ![Search results](11-search-results.png) Global full-text search across tickets and documents. | ![Client portal](15-client-portal.png) The public client portal -- file a request with no account, with an at-a-glance status strip once signed in. |
| ![Admin branding](14-admin-branding.png) Runtime branding and the public-portal settings, no redeploy needed. | ![Home](02-home.png) The landing page, driven by a flagged document. |

![Sign in](01-login.png)

Sign in -- local, LDAP, and SAML accounts all use this same form.
