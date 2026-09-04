# RAIN User Guide

Walks through RAIN screen by screen: what each page is for, what you
can do on it, what options it offers. For how the system is built,
see [`architecture.md`](architecture.md); for every database table,
[`database-schema.md`](database-schema.md); for where things live in
the codebase, [`code-layout.md`](code-layout.md).

## Signing in

Email and password. The same form handles local accounts (checked
against a local password hash) and LDAP/Active Directory accounts
(checked by binding live against the directory). If SAML is enabled,
a "Sign in with SSO" button appears below the password form.

If an SMTP relay is configured (Admin → Settings), a "Forgot password?"
link appears for local accounts: sends a one-hour, single-use reset
link, with the same confirmation message whether or not the address is
registered. Resetting a password signs that account out everywhere
else. LDAP and SAML accounts have no local password -- reset your
directory or IdP password instead. No SMTP relay, no link: ask an
admin to set your password from Admin → Users.

### First-run setup

A fresh instance shows a one-time setup wizard instead of the login
page:

- Instance name, accent color, an optional logo (PNG, JPEG, SVG, WebP).
- First tenant's name and slug (the slug becomes part of its schema
  name -- keep it short and lowercase).
- First internal admin account: full name, email, a 10+ character
  password.

Stored in Postgres, editable later from Admin. Runs once -- after the
first admin account exists, this URL shows the login page.

## Finding your way around

Every signed-in page shares the same shell: sidebar, topbar, content.

### Sidebar

Records Authority (tickets), Calendar, Assets, Documents, and, for
admins, Admin. Each expands into a submenu. Several entries carry a
live count badge (open incidents, documents in the repository, ...).

A "Quick Navigation" box filters the sidebar as you type. It resizes
by dragging its edge, and collapses to icons from the topbar's "Menu"
button on narrow screens.

### Topbar

Left to right: a breadcrumb with a "?" tooltip for the current page, the
global search bar, a "Session for `<tenant name>`" pill, and the user
menu (display name, role badge, current schema build number, sign out).

### Search

Typing a word or phrase searches ticket and document titles,
descriptions, numbers, and (for documents) tags, ranked by relevance,
opening a results page with highlighted snippets.

Typing an exact record number (`INC-000001`, `VULN-000004`,
`CHG-000012`, `DOC-000002`) opens that record directly. Every ticket
and document lives at a URL built from its number.

### Pagination

Every list screen -- tickets, assets, documents, users, admin lists --
shows a "Showing 1 to 25 of 340" summary with Prev/Next. Page size is
fixed per list, not user-configurable.

## Home

The first sidebar item, shown after signing in. Default: a plain
"Welcome to `<instance name>`". To replace it, open a Markdown or
plain-text document and check "Show on landing page" under its
Properties tab -- its content renders here instead (Markdown formatted,
plain text as-is). Several documents can be checked at once, shown in
title order, each with a "Version from `<timestamp>`" pill.

## Tickets

Labeled "Records Authority" in the sidebar. One form, one detail page,
one export pipeline, three record types:

- Incidents (`INC-xxxxxx`): something is actively wrong.
- Vulnerabilities (`VULN-xxxxxx`): a weakness needing remediation.
- Changes (`CHG-xxxxxx`): planned work needing approval.

Submenu: Events (the live syslog feed), Incidents, Vulnerabilities,
Changes (filtered ticket-list views), Kanban, Service Catalog, Custom
Fields, Export, Import.

### Ticket list

One shared list, pre-filtered by type from the sidebar entries:

- "+ New ticket" button.
- Type pills (All, Incidents, Vulnerabilities, Changes).
- A status dropdown, filtered to one tenant-defined status.
- Quick-filter chips: Mine, Unassigned, Problematic, Prioritized (high/
  critical severity).
- A Normal/Condensed row-spacing switch, remembered per browser (shared
  with the Events tab's own switch). Display only.
- A sortable table (Number, Title, Severity, Status, Created); Assignee
  and Asset are shown but not sortable, Asset links to its own page.
- A three-dot row menu per ticket, matching the detail page's own
  button row: Mark/Unmark problematic, Watch/Stop watching, Promote to
  Change (incidents/vulnerabilities only), Escalate (once configured),
  Analyze root cause, plus list-only quick actions Mark closed and Mark
  cancelled (changes only), and Get a hard copy (PDF).

A change ticket's title carries a small approval-status icon; a
problematic ticket shows a recurring-arrow icon.

### Kanban board

Same tickets and filter bar as the list, laid out in columns. A "Group
by" dropdown picks the columns:

- **Status** (default): one column per tenant-defined status. Drag a
  card to move it, same as the status stepper on the detail page.
- **Assignee (workload)**: one column per assignable user plus
  "Unassigned" first. Drag to assign or clear. A ticket assigned to
  someone no longer assignable shows in its own "not assignable here"
  column -- draggable out, not back in. A group filter (Admin >
  Groups) narrows which people get a column; dragging still assigns to
  the individual.

A card reverts to its original column if a move doesn't go through. A
board caps at 500 matching tickets, with a banner if a filter set
turns up more -- narrow the filters or use the table view.

Each card: ticket number, problematic/approval icons, severity badge,
title, assignee, asset, and the same three-dot menu as the list.

### New ticket

Reached from "+ New ticket" or a live event's "promote" action:

- Type: incident, vulnerability, or change.
- Severity: low, medium, high, critical.
- Affected asset (optional), Assignee (optional): type-to-search
  pickers.
- Title (required), Description (optional).

Type = Change adds a start/end date-time and a required approval flow
(the tenant's default flow, if any, pre-selected). No flows yet means
no change tickets until one exists (Admin > Approval Flows).

Arriving from an event or another ticket's "Promote to Change" action
pre-fills title/description and notes the source.

Any tenant-defined ticket custom fields (Records Authority > Custom
Fields) appear as a "Custom fields" section at the bottom.

### Ticket detail

A status stepper (one button per tenant-defined status) at top;
clicking any status moves the ticket there. Quick actions next to it:
Promote to Change (incidents/vulnerabilities), Mark/Unmark problematic,
Watch/Stop watching (email on new comments and status changes; the
reporter and assignee watch automatically), Escalate (renamable under
Admin > Branding, shown once an escalation webhook is configured --
fires it for this ticket, shows the response, and posts it as a
comment), Analyze root cause (a repeat-occurrence pattern plus similar
closed tickets by title/description match -- statistical signals, not
a determined cause; Post as comment, Copy, or Close), and Export to
PDF. The list row menu and Kanban card menu mirror this whole button
row.

Below that:

- Priority badge, editable inline (pencil icon → dropdown → Save).
- Problematic badge, if flagged.
- Type badge, Created timestamp pill.
- Title, editable inline the same way.
- Description: read-only text (edit via the Activity feed's comment
  box, or wherever the ticket originated).
- A metadata table: Assignee/Asset (inline pickers), Reported by (user,
  or the Event Promotion Policy that auto-created it), Source event
  (opens the same event-preview window Events uses), Promoted from (a
  link, if applicable), Change window (change tickets only).
- Document links, with an inline "Add link" control.
- If custom fields are defined, a Custom fields card with one Save
  button for the whole set.

Editing title/severity/assignee/asset on an already-approved change
prompts a confirmation, since it clears the recorded approval.

Change tickets get an Approval card: the flow's name, overall status,
and each step (who's assigned -- a group or a person -- and whether
done, current, or skipped). If you're eligible to decide the current
step, Approve/Reject (with an optional comment) appears; otherwise it
shows who it's waiting on. No flow attached yet: a form to attach one.

The Activity feed at the bottom is a single chronological history:
comments (add from the box at top; Newest/Oldest first toggle), plus
every status change, assignee/asset change, title/severity edit,
approval decision, document link/unlink, Escalate click, and Platform
Response Rule firing, each naming who or what caused it and when.

### Events (live feed)

Records Authority > Events: the live syslog stream. A status pill
shows connection state; Pause freezes the list. A Normal/Condensed
switch (shared preference with the ticket list) tightens row height.
Two filters: free-text (host/program/message) and a minimum-severity
dropdown.

CEF, JSON, and Splunk-style key=value bodies are auto-detected and
parsed, no configuration needed -- a badge (CEF/JSON/KV) marks these,
with a readable one-line summary pulled from the format's own message
field. Click a row (or "View full message") for the full event: host,
program, severity, complete message, parsed fields, raw body -- the
same window a ticket's "Source event" link opens.

Checking one or more events reveals bulk actions: "Turn these into
incidents", "Turn these into vulnerabilities", "New policy from
selection" (jumps to Event Promotion Policies, pattern pre-filled), and
"Discard these". Events never promoted are dropped after the tenant's
retention window regardless.

### Custom Fields (tickets)

Records Authority > Custom Fields. None defined by default. Unlike an
asset custom field, a ticket field always applies tenant-wide across
all three types -- no per-type scoping, no Required option (several
automated paths -- Event Promotion Policies, the client portal, Service
Catalog -- create tickets without knowing about custom fields, so a
required one would silently break those). A table lists every field
(key, label, type). "+ New custom field":

- Key: internal, lowercase identifier.
- Label: shown on forms.
- Field type: Text, Number, Yes/No, Date, URL, Email, Select.
- Select options (comma-separated), for Select only.

Once defined, a field is capturable on the New ticket form, editable on
the detail page, and importable/exportable alongside built-in columns.
Bulk-defining a set from a spreadsheet is a Tenant Administration task
-- see "Import Ticket Field Pack" under Admin.

### Export (tickets)

Records Authority > Export. Filter by type and status, pick a format
(CSV, JSON, Excel), and configure a per-column table (checkbox, source
field, editable header, order); custom fields appear alongside built-in
columns. Save the layout under a name for reuse; saved profiles list
below with a "Load" link.

### Import (tickets)

Records Authority > Import. Upload a CSV, JSON, or `.nessus` file, then
map columns to Type, Title, Description, Severity, Dedup key, and any
custom fields -- Type and Title required, the rest optional. Each row
becomes an incident or vulnerability ticket; a Change row is rejected
(a change needs an approval flow, which a spreadsheet can't express --
file those by hand). The result screen reports how many tickets were
created (and, with a Dedup key, reopened or unchanged) and lists any
per-row errors or warnings.

A `.nessus` file (the plain-XML scan export, not the proprietary
Nessus DB format) arrives pre-mapped: Info-severity findings are
dropped before becoming rows; everything else -- Type, Title,
Description, Severity, Dedup key, and, if
`docs/compliance-templates/nessus-finding-fields.rain` is imported, the
scanner metadata fields -- is filled in and still reviewable. The
template is optional; the import creates real, deduped vulnerability
tickets either way.

Dedup key makes re-running the same import safe on a recurring basis:
map it to a column unique per row (a scan's own finding ID, or a
combined host+port+plugin ID), and each row is looked up by that value.
No match creates a new ticket. An open match is left alone (only its
custom field values refresh -- title/description/severity are never
overwritten). A closed match is treated as a regression: reopened,
flagged Problematic, commented with which import caused it. Leave it
unmapped for a plain one-time import. See
[`docs/drift-detection.md`](drift-detection.md) for the closest sibling
pattern, and `docs/compliance-templates/nessus-finding-fields.rain` for
a ready-made field set.

### Service Catalog

Records Authority > Service Catalog (also on the client portal's
Request Something tab, open to every visitor). A list of requestable
services, each a short form. Fill it in and submit: creates an
incident, vulnerability, or change ticket, with your answers as its
description (JSON or `key=value` lines, e.g. `username=jdoe`,
`domain=IBM`), and, for a change service, an approval flow already
attached. The ticket detail page notes which service produced it.

Defining a service is a Tenant Administration task -- see Service
Catalog under Admin.

## Automation

Two rule types turn syslog and ticket activity into action, both under
Admin > Tenant Administration.

### Event Promotion Policies

Tickets > Rules (Admin > Tenant Administration > Event Promotion
Policies). A policy checks every incoming syslog event whose `Match on`
field matches its `Pattern` (regex). Promotion type:

**Single event** -- a match becomes its own new ticket.

**Repetition** -- a match's computed title (Title template) is checked
against already-open tickets of this type; an exact match folds the
occurrence into that ticket (a comment, flagged Problematic) instead of
creating a new one. No match: created as usual.

"Also flag statistically unusual occurrences" (default on) adds anomaly
detection on top, using the same model as ML anomaly at its standard
settings. A statistically unusual repeated event adds a note to
whichever ticket it was folded into (or the new one it started).

**ML anomaly** -- an online model learns this policy's normal traffic
(severity, message length, time of day) and fires its own ticket on an
event that doesn't fit, instead of any fixed pattern. Best for a broad
or unfiltered stream (a blank/`.*` pattern); for a specific pattern
already Repetition-tracked, the checkbox above is usually the better
fit.

- Algorithm: **Half-Space Trees** (default) -- general-purpose, best at
  a single far-outside-norm event. **Local Outlier Factor** -- better
  at values unusual for a specific time/place, pricier per event.
  **One-Class SVM** -- best when normal behavior is stable and
  anomalies are moderate.
- Group by: none, host, or program -- one model tenant-wide, or one per
  distinct value.
- Re-arm cooldown (minutes): once fired, won't fire again until this
  many minutes pass.
- Anomaly score threshold: how unusual (0-1) a new event must score to
  fire.
- Warm-up events: how many events before the model can fire at all.

A firing ticket names the single most-deviated feature and how many
standard deviations off, once enough history exists.

**Single** and **Repetition** compete for each event -- the first
matching one (by Order) wins. **ML anomaly** policies never compete;
every active one scores the event regardless.

Fields on every policy: Name; Ticket type; Severity; Match on
(message/host/program); Pattern (blank matches everything); Order
(Single/Repetition only); Title template (`{message}`, `{host}`,
`{program}`, plus `{count}`/`{window}`/`{score}` for ML anomaly);
Auto-link asset by (match host/program against an asset's External ID,
optional); Approval flow (change only -- which flow to attach, or none;
a policy-produced change defaults to a 24-hour window starting
immediately, editable after).

A "Test" button per row checks a pasted sample line against the current
pattern without creating anything. A training-status badge shows for
ML anomaly or flagged-Repetition policies: "No events yet", "115/250
training", "Live", or a grouped summary. The edit page breaks this down
per group.

An Active checkbox disables a policy without deleting it -- its events
fall through to the next policy, or stay unpromoted.

Events' selection menu has "New policy from selection", pre-filling a
pattern from the selected event(s) on the Repetition tab.

### Platform Response Rules

Tickets > Platform Response Rules. React after a ticket exists
(created any way) or after a document's acknowledgment requirement is
set. Every active matching rule fires, not just the first, and each can
run several actions.

"New rule" asks for name, trigger, match on (title/description),
pattern, order, then opens the rule's detail page to add actions.
Trigger: incident/vulnerability/change created; one of those three
closed; a change fully approved; a document entering "pending
acknowledgment".

Actions, any number per rule:

- Notify Slack / Notify Email: pick a notification channel -- delivery
  actually follows the channel's own type, not the action label.
- Call a webhook: pick a webhook definition.
- Attach a document / Attach an asset (as the ticket's affected asset).
- Mark problematic.
- Add a watcher: an email address, or a system user (not both).

The last four apply only to tickets -- on a document-acknowledgment
rule they're skipped, harmless if attached by habit. Notify/webhook
actions work either way, filling in `{{doc_number}}`, `{{title}}`,
`{{description}}` for a document trigger.

Every firing and its actions' outcomes are logged to the rule's own
history and (for a ticket trigger) to the ticket's Activity feed,
success or failure.

Below the rule list: "Automatically analyze root cause when a ticket
closes" (off by default) runs Analyze root cause once, the first time a
ticket moves into a closed status.

## Calendar

Per-tenant, submenu Month View and New Entry.

### Month view

A Sunday-Saturday grid with Prev/Next, "+ New entry" on today, .ics
export/import. Each day shows a "+" and a chip per entry or change-
ticket window; clicking opens it for editing. Recurring entries carry a
loop icon.

### New / edit entry

- Title (required), Date, Description (optional).
- Repeats: one-time, daily, weekly, monthly, quarterly, every 6 months,
  annually.
- Repeat until (optional cutoff date).
- Active (edit only): unchecking hides without deleting.

Two optional behaviors:

- Syslog bridge: "Emit syslog event on occurrence" synthesizes a
  syslog event (host `calendar`) each occurrence, matchable by Event
  Promotion Policies. Optional "Event program" value; defaults to the
  title.
- Related document: shows this entry on that document's Calendar tab.
  "Also auto-refresh it from its webhook on each occurrence" additionally
  refreshes the document each time -- only takes effect if the document
  has a webhook configured.

Delete on an existing entry's edit page, with confirmation.

### Import

Pick an `.ics` file. Best-effort: reads `SUMMARY`, `DESCRIPTION`,
`DTSTART`, `RRULE` (a yearly rule → Annually; a 3- or 6-month interval →
Quarterly or Every 6 months); everything else ignored. Reports how many
entries were created.

## Assets

Submenu: All Assets, By Type (one entry per asset type), Custom
Fields, Export, Import.

### Asset list

A table (Name, Type, External ID, Status) with a type filter, Edit/
Delete per row, "+ New asset".

### New / edit asset

- Name (required).
- Asset type: changing it swaps which custom fields show below.
- External ID (optional): serial/tag/cloud resource ID -- also what
  Event Promotion Policies match against for auto-linking.
- Status: active, in_repair, retired, decommissioned.
- Custom fields for the selected type.

Editing shows Export to PDF, document links with "Add link", and a
read-only Linked Tickets table.

### Custom Fields

Assets > Custom Fields (also under Admin > Tenant Administration >
Asset Types). A table of every field: applies-to type (or "All
types"), key, label, type, required. "+ New custom field":

- Applies to: one type, or All types.
- Key, Label.
- Field type: Text, Number, Yes/No, Date, URL, Email, Select.
- Select options (comma-separated).
- Required.

### Asset Types

Also under Admin > Tenant Administration > Asset Types. A table (Key,
Name, field count, Active) with "+ New asset type" (Key, Name, optional
icon, optional description). Deleting a type deletes every asset of
that type -- the confirmation says so.

### Import

Three steps. Assets > Import: pick asset type, format (CSV or JSON
array), file. Column-mapping screen: map each target field, "-" to
skip; auto-suggested from header names. Result screen: rows created
vs. updated (matched/updated by External ID; unmatched rows created
new), plus per-row errors.

### Export

Assets > Export. Pick an asset type (or "All types" for built-in
columns only), the same column table as every export screen, a format
(CSV/JSON/Excel), and an optional saved-profile name.

## Documents

Submenu: All Documents, Upload.

### Document list

A table (Number, Title, Tags, File, Uploaded) with a search box
(title/number/tag) and "+ Upload document".

A document's number carries flag icons:

- Home icon: shown on the Home page.
- Refresh icon: populated from a webhook (tooltip notes whether it
  auto-refreshes on view or only on manual "Refresh from webhook").
- Calendar icon: linked to a calendar entry.
- Shield icon: shareable in the client portal (tab commonly renamed
  "Trust Center" -- see Branding under Admin).
- Warning icon: overdue for review (past its Properties-tab review
  date).

A tag dropdown narrows to one tag; each tag in the Tags column is also
a link. An "Overdue for review" checkbox narrows to only documents past
their review date -- a document with no review date set is never
overdue, only untracked.

### Documents Kanban board

"Kanban view" from the document list, or Documents > Kanban. Same
documents, columns via a "Group by" dropdown:

- **Tag** (default): one column per tag, deduplicated case-
  insensitively ("security"/"SECURITY"/"Security" collapse to one
  column). "Uncategorized" holds untagged documents. A multi-tag
  document appears in each column; dragging to a different tag column
  retags it (removes the origin tag, adds the target, leaves others).
  Dropping on a tag already present just removes the origin; dropping
  on Uncategorized removes it entirely.
- **Owners**: one column per assignable user plus "No owner" first.
  Drag to assign or clear. A group filter narrows to one team.

The other mode is available as a plain filter in either view (Filter by
person in Tag mode, Filter by tag in Owner mode).

Each card: number (with flag icons), title, current owner. A move
reverts with an error banner if it didn't go through.

### New document

Labeled "Upload document" but offers two tabs:

- Upload a file: up to 25MB.
- Type new content: `.txt` or `.md`, typed directly -- for a
  placeholder document with nothing to upload yet.

Title (required), Description, Tags (comma-separated) apply to either
tab. Arriving from another record's "link a document" action attaches
the new document automatically.

### Document detail

Header: Download, Export to PDF, Delete. Tabs:

- **Properties**: tags as editable badges. Owner (type-to-search,
  independent of who uploaded it). Review due date -- past it, the
  document shows the overdue icon and the list's overdue filter. An "I
  have read this" button plus a per-person acknowledgment log. "Requires
  acknowledgment from" (a group or person) makes acknowledgment
  mandatory: everyone it resolves to gets emailed and shows up under
  their own Pending Actions in the [Client Portal](#client-portal) until
  they click "I have read this" -- clicking Request again re-opens it
  for anyone who'd already acknowledged. "Shareable in the client
  portal" exposes it on the [Client Portal](#client-portal)'s Shareable
  documents tab to every visitor, including anonymous ones, regardless
  of require-sign-in -- off by default. "Show on landing page" does the
  same for [Home](#home). An Uploaded date pill. A Description
  textarea, saved independently of the file.
- **Contents** (`.txt`/`.md` only): a "Last updated" label (last webhook
  refresh, or last manual save), then an inline editor. Markdown gets a
  Write/Preview tab using the same renderer as PDF export. Saving diffs
  against what's stored -- no real change means no change recorded.
- **Auto-update** (`.txt`/`.md` only): pick a webhook to populate
  content from; "Emit syslog alert on change" raises an event (Event
  Promotion Policy-eligible) whenever the stored content actually
  changes, from either a webhook refresh or a manual save, with a
  compact added/removed-lines diff. "Refresh when rendering" (off by
  default, needs a webhook picked) re-runs the webhook and updates
  content on every display of this page or of Home (if also flagged
  "Show on landing page"). A failed call falls back to the last saved
  version; this page shows a notice, Home falls back quietly. "Refresh
  from webhook" appears once a webhook is set, with the last-refresh
  timestamp; each refresh diffs against what's stored.
- **Links**: every linked ticket/asset, with Unlink, and an "Add link"
  control (pill selector, then a ticket number or asset ID).
- **Calendar**: every tied calendar entry (Title, Date, Repeats, an
  auto-refresh badge), with Edit/Delete and "+ New reminder".

## Search results

Reached by typing anything other than an exact record number. A ranked
table of matching tickets and documents (Type badge, number, title with
a highlighted snippet) -- a document can match on tags too. "No
matches" if nothing found; an empty search box shows a prompt instead.

## Client Portal

`/portal/<tenant slug>` -- no sidebar or topbar. Every visitor, signed
in or not, sees:

- **Request Something** (default tab): the same [Service
  Catalog](#service-catalog) as the main app.
- **Report Something**: the incident report form, and "Tickets reported
  by me" (only once signed in).

Both tabs accept submissions with or without a session, gated by
`portal_require_auth` (below) -- an unauthenticated submission records
"an unauthenticated user" as reporter.

**Signed in** additionally gets a search bar and:

- **Pending Actions**: change tickets waiting on your decision (a
  closed/cancelled-without-decision change drops off this list), plus
  documents requiring your acknowledgment -- an "I have read this"
  button clears one directly.
- **Document Archive**: every document in the repository, linked out.

Report Something's ticket table gains an Escalate button once signed
in, if an escalation webhook is configured.

Clicking a ticket number opens a lightweight timeline (status changes,
comments, assignment/asset changes, approval decisions) instead of
navigating away, with an "Edit ticket" button to the full page.

**Today's events**, above the tabs: calendar entries and change-ticket
windows due today, or "None" -- shown to every visitor, capped at 5
with a "+N more" link.

**Shareable documents** (shown once at least one exists): every
document marked shareable, reachable by every visitor including
anonymous ones even with "Require sign-in" on -- in that case an
anonymous visitor sees only this tab. Renamable per tenant (e.g. "Trust
Center") under Admin > Branding.

Four settings, all under Admin > Branding > "Public incident portal"
(client_admin reaches this for their own tenant; internal_admin needs
to switch tenant first):

- **Require sign-in**: on, only signed-in tenant users can file; off,
  anyone with the link can. Shareable documents are reachable either
  way.
- **Show instance branding**: on, shows this instance's logo/name/
  accent color; off, a plain unaccented page with just the tenant name.
- **Escalation webhook**: which webhook the Escalate button calls,
  everywhere it appears. Unset: no Escalate button.
- **Escalation button label**: default "Escalate" -- rename to match,
  e.g. "Page On-Call".
- **Shareable documents tab name**: default "Shareable documents".

A signed-in visitor of a different tenant than the URL's is always
turned away with a 403, regardless of the require-sign-in setting.

### Tenant defaults

Also on Admin > Branding: **Record list page size** (10/25/50/100/200,
default 25) -- applies to Tickets, Assets, Documents, and this
tenant's admin config lists. Doesn't affect platform-level Tenants/
Users/Syslog Sources lists.

Two optional fields, blank by default:

- **Custom JS - main app**: raw HTML/JS added before `</body>` on every
  signed-in page for this tenant -- an analytics snippet, a chat
  widget, anything that ships as a `<script>` tag. Runs with full page
  access for as long as a user is signed in -- only paste something
  you'd trust as much as a new admin user.
- **Custom JS - client portal**: the same, for `/portal/<tenant>`
  instead -- reachable by anyone with the link. Independent of the
  field above.

Neither field is sanitized -- a deliberate trust boundary, not an
oversight. Neither reaches the other surface or the shared login/setup
screens.

## Roles and permissions

Three roles, assigned per user under Admin > Users:

- **Internal Admin**: platform-wide. Manages every tenant, switches
  which one is active, reaches Platform Administration.
- **Client Admin**: full admin rights, pinned to one tenant. Reaches
  Tenant Administration for that tenant only.
- **Client**: a regular user, no admin screens.

Client and Client Admin accounts require a tenant at creation/edit;
Internal Admin accounts don't belong to one.

## Admin

Visible only to Internal Admin and Client Admin, split into two
submenus matching that permission split.

### Platform Administration

Internal Admin only. Everything spanning every tenant or instance-wide.

**Branding.** Instance name, accent color, font (system/web-safe list,
nothing pulled from a CDN), button style (Square or Rounded), an
optional logo (up to 5MB; leaving the field empty on edit keeps the
current one). Applies immediately, across every tenant.

**Tenants.** A table (Name, Slug, schema name, Active) with "+ New
tenant" (Name, Slug) and a "Switch to" button per tenant.

**Auth Providers.** Local (always on), LDAP, SAML -- each shows
enabled/last-synced. Configure pages:

- LDAP: one directory. Connection (Server URI, StartTLS, Bind DN/
  password), user sync (base DN, filter, email/name attributes), group
  sync (base DN, filter, name/member attributes), target tenant and
  sync interval. Status card with last sync + "Test connection"/"Sync
  now". Synced users authenticate live against the directory, never a
  local password. One directory, one target tenant.
- SAML: one identity provider. Shows this instance's SP metadata/ACS
  URLs. Form covers IdP (entity ID, SSO URL, signing cert), SP (this
  instance's entity ID), attribute mapping (username/email/name/role,
  plus which role value grants Internal Admin -- case-sensitive,
  anything else grants Client), and a target tenant. First sign-in
  creates the user; an email already used by a local/LDAP account is
  refused. Every sign-in refreshes name/role from the assertion. One
  IdP, one target tenant.

**SMTP Relay.** One relay for the instance: Host, Port, From, Username,
Password (blank on edit keeps current), STARTTLS checkbox. Recipients
for ticket notifications are configured per tenant under Notification
Channels.

**Syslog Listener.** Listener status and TCP/UDP port. "Untreated event
retention" (hours, 0.5 min, 12 default) -- doesn't apply once an event
is promoted. A routing rules table maps incoming events to tenants (or
discards them) by host/program pattern match, with Action, Tenant,
Match on, Pattern, an optional Regex checkbox, and Order. First match
wins; unmatched events are dropped.

**Users.** A table across every tenant (Name, Email, Role, Tenant, Auth
source, Active, Last login) with Deactivate/Edit per row and "+ New
user" (Full name, Email, Password, Role, Tenant -- required for Client/
Client Admin). Editing changes name/role/tenant, resets a local
password, or deactivates. LDAP users show their bind DN instead of a
password field (sync overwrites name/tenant/active status, not role).
"Last login" plus an Export CSV button are an access-review aid for
finding dormant accounts.

**API Documentation.** A Swagger UI over every route the web app
exposes, grouped by area -- no separate API key, since it documents the
same server-rendered routes the UI already calls. For reacting to
RAIN's events externally, use Webhooks and Platform Response Rules.

**Config Bundles.** Export/import instance-wide configuration (never
ticket/asset/document data) as one `.rain` file: instance name, accent
color, font, logo, portal background, SMTP relay, LDAP/SAML config,
syslog routing rules. "Include secrets" (off by default) controls
whether SMTP/LDAP passwords come out in cleartext or redacted.
Importing upserts by name/type. A rule or provider config targeting a
tenant slug not present is skipped or imported disabled, noted in the
result. See Config Bundles under Tenant Administration for the
tenant-scoped card -- independent of this one.

### Tenant Administration

Internal Admin (for the active tenant) or Client Admin (their own).
Everything scoped to one tenant.

**Groups.** Named user sets, used as an approval-flow step target. List
shows Name, Description, member count, Source (local or LDAP). "+ New
group" (Name, optional Description). A group's page: member list with
Remove, a type-to-search Add member. LDAP-sourced groups note that
membership is overwritten on every sync.

**Ticket Statuses.** The tenant's own status set, replacing a fixed
open/closed enum. Table: Order, Status (colored pill), Key, "counts as
closed" (stamps a closed date), Active. "+ New status" (Label, Key,
Color, "Counts as closed", Order). Deactivating/deleting a status
doesn't affect tickets already set to it. (The "Root cause assistance"
toggle lives under Platform Response Rules, not here.)

**Notification Channels.** Named destinations a Platform Response Rule
notifies. Type (email/Slack/webhook) plus Name; fields depend on type
(email: comma-separated Recipients; Slack: incoming webhook URL;
webhook: pick an existing definition). Email/Slack channels expose an
editable Message (email also gets Subject), with placeholders
`{{ticket_number}}`, `{{title}}`, `{{description}}`, `{{severity}}`,
`{{status}}`, `{{ticket_type}}`.

**Approval Flows.** Named, ordered processes a change attaches to.
List: each flow's steps, a "syslog on approval" badge, and which is
default (with "Make default"). Creating/editing: Flow name, "Make
default", "Emit syslog on full approval" (off by default), and a
variable number of steps (Label, Group, individual user via type-to-
search -- if both set, the group wins). A step doesn't open until the
one before it clears. The syslog checkbox fires a synthetic event on
final approval, matchable by Event Promotion Policies.

**Service Catalog.** List: Name, Key, Produces, Format, Approval flow,
question count, Active. "+ New service":

- Name, Key (URL slug), Description, Active.
- Produces (ticket type), Severity (fixed per submission), Payload
  format (JSON or `key=value`).
- Requires approval + Approval flow picker (shown only for Produces =
  Change; a Change service must require approval to save).
- Up to 10 questions, each: field_key, Question text, Type (Text,
  Number, Yes/No, Date, URL, Email, Select), Options (Select only),
  Required.
- Optional per-question Source document + Source mode to pull its
  value from an existing document instead of free entry -- Content
  (whole document, each line an option for Select), Regex or JSONPath
  extract. A Select question gets every match as an option; other
  types get the first as a prefilled default. Preview checks what a
  pattern resolves to.

**Import Ticket Field Pack.** Bulk-defines ticket custom fields from a
spreadsheet. Upload CSV/Excel with a header row naming fields (sample
data rows let it guess a type; header-only works too, everything starts
Text). Next screen: detected columns, guessed key/label/type, all
editable, an Include checkbox (off by default for an existing key).
Result: fields created, and any skipped (duplicate key, missing key/
label).

**Webhooks.** Centrally-defined outbound calls, reused by Platform
Response Rules, document auto-update, notification channels, and
Escalate. List: Name, Method, URL, Timeout, Success codes. "+ New
webhook": Name, HTTP Method, URL, Timeout, Success codes (comma-
separated), Headers (one `Name: value` per line), Payload template
(JSON, ignored for GET) using the same double-brace placeholders as
notification channels, "Emit syslog alert on failure" (off by default).

**Placeholders reference.** Two independent placeholder systems -- the
wrong syntax in the wrong field is left as literal text:

- Double braces (`{{ticket_number}}`): a webhook Payload template or
  notification channel Message/Subject. Fill in `{{ticket_number}}`,
  `{{ticket_type}}`, `{{title}}`, `{{description}}`, `{{severity}}`,
  `{{status}}` from whichever ticket triggered the call. A document's
  webhook refresh calls with none of these -- keep that payload static.
- Single braces (`{message}`): an Event Promotion Policy's Title
  template (plain Python formatting, deliberately distinct so it
  doesn't misparse a JSON payload's own braces). `{message}`, `{host}`,
  `{program}`, plus `{count}`/`{window}`/`{score}` for ML anomaly.

**Asset Types.** Covered under Assets above.

**Config Bundles.** The same page Platform Administration's Config
Bundles points at, showing only this tenant's card: asset types, custom
fields, ticket statuses, groups, local users, notification channels,
webhooks, approval flows, Event Promotion Policies, Platform Response
Rules, Service Catalog items -- as one `.rain` file. Every internal
reference (a rule's channel, a step's group, ...) is written by name,
so it resolves in a different tenant too. An action or field pointing
at a specific document/asset has no portable equivalent and is skipped,
noted in the result, same as an unresolvable group/step. "Include
secrets" controls whether channel/webhook config and password hashes
carry across -- without it, a matching-email account is recognized but
a new one has no password. Importing upserts by name/key; a local user
is never overwritten once it exists.

The same Import expects any tenant bundle, including the twelve starter
compliance-register templates under `docs/compliance-templates/` --
import one for a usable register in a few clicks instead of building
the asset type by hand. All but the three ticket-scoped templates
(POA&M, Nessus, FedRAMP OCR) are an asset type plus its custom fields;
see [`docs/compliance-templates/README.md`](compliance-templates/README.md)
for what each one seeds.
