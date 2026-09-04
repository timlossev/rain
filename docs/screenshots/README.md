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
| ![Event Promotion Policies](12-event-promotion-policies.png) Event Promotion Policies turn matching syslog events into tickets automatically. | ![Platform Response Rules](13-platform-response-rules.png) Platform Response Rules react to ticket lifecycle events -- notify, tag, escalate. |

## Assets, documents, calendar

| | |
|---|---|
| ![Asset list](07-asset-list.png) The asset registry, with no-code custom fields per type. | ![Document list](08-document-list.png) The document repository, with tags and status flags. |
| ![Document detail](09-document-detail.png) A document's own page -- properties, contents, links, calendar. | ![Calendar](10-calendar.png) The per-tenant calendar, with recurring entries and a syslog bridge. |

## Search, portal, admin

| | |
|---|---|
| ![Search results](11-search-results.png) Global full-text search across tickets and documents. | ![Client portal](15-client-portal.png) The public client portal -- file a request with no account. |
| ![Admin branding](14-admin-branding.png) Runtime branding and the public-portal settings, no redeploy needed. | ![Home](02-home.png) The landing page, driven by a flagged document. |

![Sign in](01-login.png)

Sign in -- local, LDAP, and SAML accounts all use this same form.
