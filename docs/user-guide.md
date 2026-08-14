# RAIN User Guide

This is a task-oriented guide to using RAIN day to day: tickets, assets,
documents, calendar, search, and the admin console. For how the system
is built, see [`architecture.md`](architecture.md).

## Signing in

Sign in with your email and password on the login page. If your
organization uses LDAP/Active Directory, use the same form; RAIN checks
your credentials against the directory and there is no separate LDAP
password to remember. If SAML SSO is enabled, a "Sign in with SSO"
button appears below the password form.

Once signed in, the sidebar and topbar appear. The pill next to the
search bar ("Session for <tenant name>") always shows which tenant's
data is currently on screen. If you're an internal admin managing more
than one tenant, switch which one you're looking at from Admin >
Tenants > "Switch to".

Your user menu (top right) shows your name, role, and the database
schema build number, useful when reporting a bug.

## Finding things

The search bar at the top of every page searches ticket and document
titles, descriptions, and numbers. Results are ranked and show a
highlighted snippet of the match.

Typing an exact ticket or document number (`INC-000001`, `VULN-000004`,
`CHG-000012`, `DOC-000002`) jumps straight to that record instead of a
results page. Every ticket and document lives at that same
human-readable URL, so a bookmark or a link pasted in chat stays
meaningful.

## Tickets

RAIN tracks three kinds of tickets, sharing one record type, one
activity feed, and one export pipeline:

- **Incidents** (`INC-xxxxxx`): something is wrong right now.
- **Vulnerabilities** (`VULN-xxxxxx`): a weakness that needs remediation.
- **Changes** (`CHG-xxxxxx`): planned work that needs approval before
  it happens.

### Creating a ticket

Use "+ New ticket" from the Tickets list, or promote one from a live
syslog event (see below). Every ticket has a title, description,
severity (low, medium, high, critical), status, and optionally an
assignee and a linked asset. A change ticket additionally requires
picking an approval flow and a scheduled start/end window; that window
also shows up on the tenant calendar automatically.

Title, severity, status, assignee, and linked asset can all be edited
after creation. Every change is recorded on the ticket's activity feed,
so there's always a history of who changed what and when.

### Activity feed

Each ticket has one chronological feed combining comments, field
changes, assignment and asset changes, approval decisions, and any
automation that fired because of the ticket. Sort it newest or oldest
first from the toggle at the top of the feed.

### Chronic tickets

Flag a recurring issue as chronic to make it stand out in ticket lists.
It's a visual marker only; it doesn't change how the ticket behaves.

### Statuses

Each tenant defines its own set of ticket statuses (not a fixed
open/closed pair). One of those statuses is marked "closed" for
reporting purposes; everything else counts as active. A tenant admin
manages the list under Admin > Ticket Statuses.

### Exporting

Export any ticket to a branded PDF, including its full activity
history, from the ticket detail page. Export a filtered list of tickets
to CSV, JSON, or Excel from Tickets > Export.

## Live events and automation

RAIN includes a built-in syslog listener. Point a syslog-ng destination
at it (Admin > Syslog Listener shows the port and status) and matching
events start appearing on the Tickets > Events live feed. From there
you can promote an event into a ticket, correlate it, or discard it,
individually or in bulk.

Three kinds of rules automate this, all managed under Admin > Tenant
Administration:

- **Event Promotion Policies**: a regex against an event's host,
  program, or message that auto-creates an incident or vulnerability
  ticket when it matches.
- **Correlation Rules**: like a promotion policy, but only fires once N
  matching events land within a trailing time window (optionally
  grouped per host or program). Useful for "don't open a ticket on the
  first failed login, only after five in ten minutes."
- **Platform Response Rules**: react after a ticket already exists
  (regardless of whether it came from a promotion rule or was created
  by hand). Each rule can notify Slack or email, call a webhook, or
  attach a document or asset. Every matching rule fires, and every
  firing is logged to the ticket's activity feed, whether or not the
  action itself succeeded.

An event that never gets promoted into a ticket is discarded after a
retention window (12 hours by default, adjustable in Admin > Syslog
Listener). A promoted event's ticket keeps working normally regardless
of that setting.

### Notification channels

A notification channel is a named destination: email addresses, a
Slack incoming webhook, or a reference to an existing webhook
definition. Manage them under Admin > Notification Channels, where you
can also customize the message (and, for email, the subject) a
Platform Response Rule sends. Use `{{ticket_number}}`, `{{title}}`,
`{{description}}`, `{{severity}}`, `{{status}}`, and `{{ticket_type}}`
in either field; they're substituted with the actual ticket's values
when the notification goes out.

### Webhooks

Webhooks are configured once, centrally, under Admin > Webhooks: a URL,
HTTP method, headers, payload template, timeout, and which response
codes count as success. That one definition can then be reused by a
Platform Response Rule, a notification channel, a document's
auto-populate setting, or a calendar entry's auto-update, instead of
entering the same URL in four places. Turn on "alert on failure" to get
a syslog event (and, if a matching promotion rule exists, a ticket)
when a call fails or times out.

## Assets

The asset registry tracks anything your organization inventories:
servers, laptops, licenses, whatever a tenant defines. Each asset
belongs to an asset type, and each type can have its own custom fields
(text, number, boolean, date, URL, email, or a select list). Asset
types and their fields are managed under Admin > Asset Types.

Import assets from CSV, JSON, or Excel, with a reusable column mapping
profile so repeat imports don't need re-mapping. Export the same way.
Any ticket linked to an asset shows up on that asset's own page and in
its PDF export.

## Documents

Documents are numbered `DOC-xxxxxx` and can be linked to any ticket or
asset. When creating one, either upload a file or type content directly
(saved as `.txt` or `.md`); a placeholder document doesn't require an
upload at all.

To link an existing ticket or asset to a document, use the pill on the
document's Links tab to pick Ticket or Asset, then enter the ticket
number (`INC-000123`) or asset ID.

A document can optionally be populated from a webhook instead of a
manual upload. Each refresh diffs the new content against what's
stored and can raise a syslog alert when it actually changes, so a
document tracking something external (a policy page, a generated
report) stays current without manual copy-pasting.

Export any document to a branded PDF; if it's webhook-populated, the
PDF notes the source and the last refresh time.

## Calendar

Each tenant has its own calendar with a month-grid view. Entries
support recurrence presets: daily, weekly, monthly, quarterly, every 6
months, annually, or one-time. Change tickets with a scheduled
start/end window appear on the calendar automatically alongside
whatever you add by hand.

Two optional behaviors, set per entry:

- **Syslog bridge**: synthesize a syslog event on each occurrence, so
  the same rule engine that reacts to real syslog traffic (promotion
  policies, correlation rules) can react to a recurring calendar entry
  too.
- **Auto-update**: point the entry at a webhook-populated document, and
  each occurrence refreshes that document, the same as clicking its own
  "Refresh from webhook" button.

Import or export the calendar as a standard iCalendar (`.ics`) file.

## Roles and permissions

RAIN has three roles:

- **internal_admin**: platform-wide. Manages every tenant, branding,
  auth providers, SMTP, and the syslog listener, and can switch which
  tenant they're viewing.
- **client_admin**: full admin rights, but confined to one tenant. Can
  manage that tenant's ticket statuses, notification channels, approval
  flows, rules, webhooks, groups, and asset types, but never sees
  platform-wide settings or other tenants.
- **client**: a regular user of one tenant, with no admin access.

The Admin console itself reflects this split: **Platform
Administration** (internal_admin only) covers branding, tenants, auth
providers, SMTP relay, the syslog listener, and platform users.
**Tenant Administration** (internal_admin or client_admin) covers
groups, ticket statuses, notification channels, approval flows, event
promotion policies, correlation rules, platform response rules,
webhooks, and asset types.

## Approval flows and groups

A change ticket can't be filed without picking an approval flow. A flow
is an ordered list of approval steps; each step can target an
individual user or a named group. Groups are just named sets of users,
managed under Admin > Groups, so a step can say "anyone on the Change
Advisory Board" instead of naming people one at a time. Editing a
change ticket's title, description, or window after it's been approved
clears existing approvals, since the thing that was approved no longer
matches what's being shipped.

## Branding and setup

The first visit to a fresh RAIN instance runs a short setup wizard:
instance name, accent color, an optional logo, the first tenant, and
the first internal admin account. After that, branding (name, color,
logo, font) stays editable under Admin > Branding, and everything else
described in this guide is configured from the Admin console as you
go. Nothing meaningful needs to be edited in a config file after first
run.
