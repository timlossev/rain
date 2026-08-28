# RAIN User Guide

This guide walks through RAIN screen by screen: what each page is for,
what you can do on it, and every option it offers. For how the system
is built underneath, see [`architecture.md`](architecture.md).

## Signing in

The login page asks for an email and a password. This same form works
for local accounts and for LDAP/Active Directory accounts: RAIN checks
local accounts against its own password hash and LDAP accounts by
binding live against the configured directory server, so there's no
separate LDAP login flow to learn. If a SAML identity provider has been
enabled for the instance, a "Sign in with SSO" button appears below the
password form and sends you to that provider instead.

If the instance has an SMTP relay configured (Admin → Settings), a
"Forgot password?" link appears under the password field for local
accounts. It sends a reset link, valid for one hour and usable once,
to the address on file; the confirmation message is the same whether
or not that address actually has an account, so the form can't be used
to test which emails are registered. Resetting a password signs that
account out everywhere else it was signed in. LDAP and SAML accounts
have no local password and don't use this flow -- reset your directory
or identity-provider password instead. If no SMTP relay is configured,
the link doesn't appear; ask an administrator to set your password
from Admin → Users instead.

### First-run setup

The very first time a fresh RAIN instance is opened in a browser, it
shows a one-time setup wizard instead of the login page. It collects,
in one form:

- Instance name and accent color, plus an optional product logo (PNG,
  JPEG, SVG, or WebP).
- The first tenant's name and slug (the slug becomes part of its
  internal database schema name, so keep it short and lowercase).
- The first internal admin account: full name, email, and a password
  of at least 10 characters.

Everything entered here is stored in Postgres and can be changed later
from the Admin console. The wizard only runs once; after the first
internal admin account exists, this same URL shows the login page
instead.

## Finding your way around

Once signed in, every page shares the same shell: a sidebar on the
left, a topbar across the top, and the page's own content in the
middle.

### Sidebar

The sidebar lists every module you have access to: Records Authority
(tickets), Calendar, Assets, Documents, and, for admins, Admin. Each
top-level entry expands into its own submenu when clicked. Several
entries carry a live count badge, for example the number of open
incidents or the number of documents in the repository, so you can see
at a glance whether something needs attention without opening it.

Above the menu is a "Quick Navigation" box that filters the sidebar as
you type, useful once a tenant has accumulated a lot of asset types or
menu entries. The sidebar itself can be resized by dragging the handle
at its edge, and collapsed to icons only from the "Menu" button in the
topbar on narrow screens.

### Topbar

The topbar shows, left to right: a breadcrumb for the current page with
a "?" icon next to it (hover or click for a short explanation of what
that specific page is for), the global search bar, a pill reading
"Session for <tenant name>" that always tells you which tenant's data
is currently on screen, and your user menu.

The user menu (the person icon) shows your display name, your role
badge, and the current database schema build number (useful when
reporting a problem), plus the sign-out button.

### Search

The search bar in the topbar is present on every page. Typing a word
or phrase searches ticket and document titles, descriptions, and
numbers (documents' tags too), ranked by relevance, and takes you to a
results page listing matches with a highlighted snippet of where the
match occurred.

Typing an exact record number instead (`INC-000001`, `VULN-000004`,
`CHG-000012`, `DOC-000002`) skips the results page entirely and opens
that record directly. Every ticket and document also lives at a URL
built from that same number, so a bookmark, a link pasted into chat, or
a link in a notification always resolves to the right record.

### Pagination

Every list screen in RAIN (tickets, assets, documents, users, and every
admin list) is paginated the same way: a summary line ("Showing 1 to
25 of 340") and Prev/Next controls at the bottom of the table. There is
no configurable page size; it's fixed per list.

## Tickets

In the sidebar this area is labeled "Records Authority", but everything
in it is what the rest of this guide, and the rest of the app, calls
tickets. It covers three record types sharing one form, one detail
page, and one export pipeline:

- Incidents (`INC-xxxxxx`): something is actively wrong.
- Vulnerabilities (`VULN-xxxxxx`): a weakness that needs remediation.
- Changes (`CHG-xxxxxx`): planned work that needs approval before it
  happens.

The Records Authority submenu has five entries: Events (the live
syslog feed, covered separately below), Incidents, Vulnerabilities,
Changes (each a filtered view of the ticket list), and Export.

### Ticket list

This is what Incidents, Vulnerabilities, and Changes in the sidebar all
point at, each pre-filtered to its type. The page itself is one shared
list with:

- A "+ New ticket" button.
- Type pills (All, Incidents, Vulnerabilities, Changes) to switch which
  type you're looking at.
- A status dropdown that filters to one tenant-defined status.
- Two quick-filter chips, "Mine" (tickets assigned to you) and
  "Unassigned", plus a "Problematic" chip that shows only tickets
  flagged problematic.
- A sortable table: click any column header (Number, Title, Severity,
  Status, Created) to sort by it, click again to reverse direction.
  Assignee and Asset columns are shown but not sortable; Asset links to
  that asset's own page when the ticket has one.
- A three-dot row menu on every ticket, matching the ticket detail
  page's own top-right button row under the same conditions -- Mark/
  Unmark problematic, Watch/Stop watching, Promote to Change (incidents
  and vulnerabilities only), Escalate (only once your tenant has an
  escalation webhook configured), Analyze root cause -- plus two
  quick actions specific to this list: Mark closed and Mark cancelled
  (changes only), and Get a hard copy (PDF).

A change ticket's title in this list carries a small icon showing
whether it's been approved yet, and any ticket flagged problematic shows
a recurring-arrow icon next to its title.

### New ticket

Reached from "+ New ticket" or from a live event's "promote" action.
The form asks for:

- Type: incident, vulnerability, or change.
- Severity: low, medium, high, or critical.
- Affected asset (optional): a type-to-search picker over your asset
  registry.
- Assignee (optional): a type-to-search picker over tenant users.
- Title (required) and description (optional, free text).

If Type is set to Change, two more fields appear: a start and end
date/time for the change window, and a required approval flow picked
from the tenant's configured flows (the tenant's default flow, if one
is marked default, is pre-selected). A tenant with no approval flows
yet can't file a change until one is created under Admin > Approval
Flows.

If you arrived here from a live event or from another ticket's
"Promote to Change" action, the page shows a note above the form
saying so, and the title/description are pre-filled from the source.

If your tenant has defined any ticket custom fields (Records Authority >
Custom Fields -- see "Custom Fields (tickets)" below), a "Custom fields"
section appears at the bottom of the form to capture them. A tenant
that hasn't defined any doesn't see this section at all.

### Ticket detail

The single-ticket page. At the top is a status stepper: one button per
tenant-defined status, with the current one highlighted; clicking any
other status moves the ticket there immediately. Next to it are
quick actions: "Promote to Change" (incidents/vulnerabilities only),
"Mark problematic" / "Unmark problematic", "Watch" / "Stop watching"
(get emailed on this ticket's new comments and status changes -- you're
watching automatically if you reported it or it's assigned to you, this
button is for anyone else), "Escalate" (only shown once your tenant has
an escalation webhook configured -- Admin > Branding -- fires it for
this one ticket on demand, filling in that webhook's placeholders from
this exact ticket -- see "Placeholders reference" under Webhooks below),
"Analyze root cause" (opens a small window with a repeat-occurrence
pattern, if this ticket accumulated more than one promoted syslog
event, and similar past *closed* tickets by title/description match --
statistical/historical signals, not a determined cause. From there,
"Post as a comment" adds it to the ticket's activity feed, "Copy to
clipboard" copies the text without posting anything, or "Close" just
dismisses it. Available regardless of the automatic-at-closure setting
below; also reachable from the same ticket's row on the tickets list,
via its own [...] menu), and "Export to PDF". The tickets list row menu
mirrors this whole button row -- Promote to Change, Mark/Unmark
problematic, Watch/Stop watching, Escalate, and Analyze root cause are
all there too, under the same conditions, alongside that menu's own
list-only quick actions (Mark closed, Mark cancelled for a change).

Below that is the main card:

- Priority (severity) badge, editable inline: click the pencil icon,
  pick a new severity from the dropdown that appears, Save or Cancel.
- A problematic badge if the ticket is flagged problematic.
- A type badge (Incident/Vulnerability/Change).
- The title, also editable inline the same way as severity.
- The description, shown as plain read-only text (edit it via the
  Activity feed's comment box instead, or from wherever the ticket was
  created).
- A metadata table: Assignee and Asset (both editable inline via the
  same type-to-search picker used on the New ticket form, each with
  its own Save button), Reported by (shows the user who filed it, or
  which Event Promotion Policy auto-created it), Source event (the
  originating syslog event ID, or "manually created"), Promoted from
  (if this ticket was promoted from another one, a link back to it),
  Change window (start and end date/time, on change tickets only), and
  Created (timestamp).
- The document links list for this ticket (see Documents below for how
  linking works) with an inline "Add link" control.
- If your tenant has defined any ticket custom fields, a "Custom
  fields" card with one Save button for the whole set -- unlike
  severity/title, these don't save individually as you edit each one.

Editing the title, severity, assignee, or asset on a change ticket
that's already been approved prompts a confirmation, because doing so
clears the recorded approval; whatever's being shipped no longer
matches what was approved, so it needs to go through approval again.

Change tickets get an additional Approval card showing the attached
flow's name, its overall status (pending, approved, or rejected), and
each step in order with who's assigned to it (a group, meaning any one
member can act, or a specific person) and whether it's done, current,
or skipped. If you're eligible to decide the current step, an Approve
or Reject button (with an optional comment) appears; otherwise the card
shows who it's waiting on. If no flow is attached yet, a small form
lets you attach one from the tenant's configured flows.

At the bottom is the Activity feed: a single chronological history of
everything that's happened to the ticket. Add a plain-text comment from
the box at the top, and toggle Newest first / Oldest first to change
the feed's sort order. Besides comments, the feed automatically shows
every status change, every assignee/asset change, every title/severity
edit, every approval decision, every document link/unlink, every
Escalate click, and every Platform Response Rule that fired because of
this ticket, each entry naming who or what caused it and when.

### Events (live feed)

The live view of the syslog listener's incoming stream, at Records
Authority > Events. A status pill in the corner shows whether the feed
is connected, and a Pause button freezes it in place so you can read
without new events pushing the list around. Two filters narrow what's
shown: a free-text filter matched against host, program, and message,
and a minimum-severity dropdown (All / Info and up / Warning and up /
Error and up / Alert and up, using syslog severity levels).

A source doesn't have to send plain syslog text -- CEF, JSON, and
Splunk-style key=value message bodies are all recognized and parsed
automatically, no configuration needed. When one is, a small badge
(CEF / JSON / KV) appears next to the message, which is itself a
readable one-line summary pulled from whatever that format's own
"this is what happened" field was, rather than the raw structured text.

Check the boxes next to one or more events to reveal a selection menu
with four bulk actions: "Turn these into incidents", "Turn these into
vulnerabilities", "New policy from selection" (jumps to Event Promotion
Policies with a pattern pre-filled from the selection, defaulted to a
Repetition policy), and "Discard these". Events that never get promoted
into a ticket are dropped automatically after the tenant's configured
retention window regardless of whether you act on them here.

### Custom Fields (tickets)

At Records Authority > Custom Fields. A default tenant schema defines
none of these -- tickets ship with no custom attributes until you add
some here. Unlike an asset custom field, a ticket one always applies
tenant-wide, across all three ticket types -- there's no per-type
scoping and no "Required" option (a ticket can be filed by several
automated paths that don't know about custom fields at all -- an Event
Promotion Policy, the client portal, a Service Catalog submission -- so
a required one would silently break those instead of just being asked
for on the manual "New ticket" form). A table of every field defined,
showing its key, label, and type. "+ New custom field" opens a form:

- Key: the internal, lowercase identifier stored on each ticket.
- Label: the human-readable name shown on forms.
- Field type: Text, Number, Yes/No, Date, URL, Email, or Select.
- Select options (comma-separated): only used when Field type is
  Select.

Once defined, a field becomes capturable on the New ticket form and the
ticket detail page's Custom fields card (see above), and importable/
exportable right alongside the built-in ticket columns (see Import/
Export below). Bulk-defining a whole set of fields at once from a
spreadsheet, instead of one at a time here, is a Tenant Administration
task -- see "Import Ticket Field Pack" under Admin below.

### Export (tickets)

At Records Authority > Export. Filter which tickets to include by type
and status, pick an output format (CSV, JSON, or Excel), and choose
which columns to include, what header text each one gets, and what
order they appear in via a per-column table (a checkbox, the source
field name, an editable header, and a numeric order) -- if your tenant
has defined any ticket custom fields, each one appears as its own
column alongside the built-in ones. Optionally save the whole column
layout under a name so you can re-run the same export later without
reconfiguring it; saved profiles appear in a list below with a "Load"
link.

### Import (tickets)

At Records Authority > Import. Upload a CSV or JSON file, then map its
columns to Type, Title, Description, Severity, and (if your tenant has
defined any) each custom field -- Type and Title are required, the rest
optional. Each row becomes a new incident or vulnerability ticket; a row
whose Type is Change is rejected rather than silently filed without one,
since a change needs an approval flow attached, which isn't something a
spreadsheet column can express -- file those by hand instead. The result
screen shows how many tickets were created and lists any per-row errors
or warnings.

### Service Catalog

At Records Authority > Service Catalog (also on the client portal's own
Request Something tab -- there, open to every visitor, signed in or
not). A list of requestable services -- "Provision a new user," "Request
VPN access," whatever your tenant has defined -- each one a short form.
Fill it in (fields marked * are required) and submit; that creates an
incident, vulnerability, or change ticket, with your answers as its
description (either JSON or `key=value` lines, depending on how the
service was configured -- e.g. a "Provision a new user" service with
Username/Domain/User type questions produces a ticket whose description
is just `username=jdoe`, `domain=IBM`, `user_type=normal`, one per
line), and -- if it's a change service -- an approval flow already
attached, just like a change ticket created manually. The ticket detail
page shows which service produced it under "Service Catalog request."

Defining a service is a Tenant Administration task -- see Service
Catalog under Admin below.

## Automation

Two kinds of rules turn the raw syslog stream and ticket activity into
action. Both live under Admin > Tenant Administration -- the first is
really about syslog events, the second about tickets.

### Event Promotion Policies

At Tickets > Rules (Admin > Tenant Administration > Event Promotion
Policies). A policy is checked against every incoming syslog event
whose `Match on` field matches its `Pattern` (a regular expression).
Each policy defines a Promotion type -- three ways to turn a match into
a ticket:

**Single event** -- the plain case: a match becomes its own new ticket.

**Repetition** -- a match's computed title (from the Title template
below) is checked against already-open tickets of this policy's type;
an exact match folds the new occurrence into that ticket instead (a
"last occurred on ..." comment, and the ticket flagged Problematic)
rather than creating a new one. No open match, and it's created as
usual. Use this for "the same kind of thing happening repeatedly should
be one ticket accumulating history, not a new one every time."

"Also flag statistically unusual occurrences" (checked by default) adds
anomaly detection on top of that -- the same kind of model the ML
anomaly type below uses, at its standard settings, no separate tuning
needed. When one of these repeated events looks statistically unusual,
a note is added to whichever ticket the occurrence was just folded
into (or the new one it started), instead of spawning a second ticket.
Uncheck it to skip this. The algorithm it uses is the same dropdown ML
anomaly has (below); everything else (group by, cooldown, threshold,
warm-up) stays at its standard value unless changed from the ML anomaly
tab itself.

**ML anomaly** -- an online model learns what this policy's traffic
normally looks like (from each matching event's severity, message
length, and time of day) and fires its own new ticket on an event that
doesn't fit, instead of any fixed pattern of repeats. Use this for
watching a broad or unfiltered event stream (a blank/`.*` pattern) that
isn't otherwise being repetition-tracked -- for a specific pattern
that's already a Repetition policy, the checkbox above is usually the
better fit, since it doesn't need a second policy definition.

- Algorithm: which model scores events, each with its own trade-off,
  picked from the dropdown (the description below it updates to match):
  **Half-Space Trees** (the default) -- a solid general-purpose choice,
  best at a single event whose values are just far outside the norm.
  **Local Outlier Factor** -- better at values that aren't extreme in
  isolation but are unusual for that particular time or place, at the
  cost of being pricier per event. **One-Class SVM** -- best when normal
  behavior is fairly stable and anomalies are moderate deviations rather
  than wild spikes.
- Group by: none, host, or program. "None" trains across every matching
  event tenant-wide as one model; "host" or "program" gives each
  distinct value its own model and, if it fires, its own ticket.
- Re-arm cooldown (minutes): once a model (or a model and group, if
  grouped) fires, it won't fire again until this many minutes have
  passed, so a burst of unusual activity produces one ticket, not one
  per anomalous event.
- Anomaly score threshold: how unusual (0-1, higher = more unusual) a
  new event's score must be to fire a ticket.
- Warm-up events: how many events the model sees before it's allowed to
  fire at all, so a brand new policy doesn't flag its own cold start as
  anomalous.

A firing ticket (or, for Repetition's checkbox above, the note it adds)
also names the single most-deviated feature (severity, message length,
or time of day) and how many standard deviations off this group's own
typical value it was, once enough history has built up to say so.

**Single** and **Repetition** policies compete for each event -- the
first one (in Order) whose pattern matches wins, so an event never
spawns two tickets that way. **ML anomaly** policies never compete for
the event the other two do: every active one still scores it against
its own model regardless of what a Single/Repetition policy above it
did.

Fields every policy has, regardless of Promotion type:

- Name.
- Ticket type to create: incident, vulnerability, or change.
- Severity to assign the new ticket.
- Match on: which event field the pattern is checked against, one of
  message, host, or program.
- Pattern: a regular expression (blank matches every event -- mostly
  useful for an ML anomaly policy, which otherwise needs no base filter).
- Order: lower numbers are evaluated first (Single/Repetition only --
  doesn't affect ML anomaly policies, which don't compete for the event).
- Title template: the new ticket's title, with `{message}`, `{host}`,
  and `{program}` placeholders (plus, for ML anomaly, `{count}`,
  `{window}`, and `{score}`).
- Auto-link asset by (optional): don't auto-link, or match the event's
  host or program against an asset's External ID field to link the new
  ticket to that asset automatically.
- Approval flow (change tickets only, ignored for incident/
  vulnerability): which flow to attach automatically when this policy
  produces a change, or "Don't attach a flow" to file an unprotected
  one. A change this policy produces also defaults its implementation
  window to starting the moment it's created, with a 24-hour
  turnaround -- edit both on the ticket afterward the same as any
  manually-created change.

Each policy row has a "Test" button that opens a small window: paste a
sample log line in and it reports whether the policy's current pattern
would match it, without creating anything. A policy also has an Active
checkbox on its edit page to disable it without deleting it -- an
inactive policy is skipped entirely, its events falling through to the
next one (or just staying in Events, unpromoted).

Events' selection menu (see Events above) has a "New policy from
selection" action that jumps here with a pattern pre-filled from the
selected event(s), defaulted to the Repetition tab -- review before
saving, every field stays editable.

### Platform Response Rules

At Tickets > Platform Response Rules. These react after a ticket
already exists, regardless of whether it was promoted automatically or
created by hand. Unlike the previous two rule types, every active rule
whose pattern matches fires, not just the first, and each one can run
several actions.

The list page's "New rule" form only asks for the rule itself: name, a
trigger, match on (the ticket's title or description), pattern, and
order. Saving takes you to that rule's own detail page to add actions.
The trigger is one of seven: an incident/vulnerability/change being
created, one of those three being closed (any status flagged "closed"
under Admin > Ticket Statuses), or a change being fully approved (its
last approval step clearing).

On a rule's detail page, its own name/trigger/match-on/pattern/order
and an Active checkbox stay editable at the top. Below that, an
"Add action" form lets you attach any number of actions, each one of:

- Notify Slack or Notify Email: pick a notification channel (see
  Notification Channels below). Which of the two you pick barely
  matters since delivery actually follows the channel's own type
  (email, Slack, or webhook), not the action's label; either one works
  with any channel type.
- Call a webhook: pick a webhook definition (Admin > Webhooks).
- Attach a document: pick a document to link to the matching ticket.
- Attach an asset: pick an asset to set as the ticket's affected asset,
  if it doesn't already have one.
- Mark problematic: flags the matching ticket problematic, same as the
  ticket detail page's own quick action.
- Add a watcher: fill in either an email address (for someone with no
  account in RAIN) or search for a system user, not both -- they start
  getting emailed on the ticket's activity the same as anyone who
  clicked "Watch" on it themselves.

Every firing of a rule, and the outcome of each of its actions, is
logged both to that rule's own history and to the matching ticket's
Activity feed, whether or not the action itself succeeded, so a failed
Slack post never hides the fact that the rule matched.

Below the rule list, a "Root cause assistance" checkbox: "Automatically
analyze root cause when a ticket closes" runs the same "Analyze root
cause" that's always available on the ticket detail page, once,
automatically, the first time a ticket moves into any status flagged
"closed" (Admin > Ticket Statuses). Off by default. It lives here
rather than on that Ticket Statuses screen since it reacts to a ticket
event (closure) the same way every rule above does, not because it's a
property of the statuses themselves.

## Calendar

Each tenant has its own calendar, reached from the Calendar entry in
the sidebar (submenu: Month View, New Entry).

### Month view

A month grid, Sunday through Saturday, with Prev/Next controls and
buttons to jump straight to "+ New entry" on today, export the whole
calendar as an `.ics` file, or import one. Each day cell shows a small
"+" to add an entry on that specific day, and a chip for every entry or
change-ticket window that falls on it; clicking a chip opens that entry
for editing (or the ticket, for a change window). A recurring entry's
chip carries a small loop icon so it's visually distinct from a
one-time entry.

### New / edit entry

Fields:

- Title (required) and Date.
- Description (optional).
- Repeats: one-time, daily, weekly, monthly, quarterly, every 6 months,
  or annually.
- Repeat until (optional): a cutoff date after which the recurrence
  stops generating further occurrences.
- Active (edit only): unchecking this hides the entry without deleting
  it.

Two optional behaviors, further down the same form:

- Syslog bridge: check "Emit syslog event on occurrence" to have each
  occurrence synthesize a syslog event (with host `calendar`) that
  Event Promotion Policies can react to, so a recurring entry (a
  quarterly access review, say) can auto-create a ticket the same way
  real syslog traffic does. An optional "Event program" value lets you
  give that synthesized event a specific program name to match on;
  left blank, it defaults to the entry's title.
- Related document: pick a document and this entry shows up on that
  document's own Calendar tab -- a plain reminder by itself (e.g. "this
  document is due for revision every quarter"), with no side effect.
  Check "Also auto-refresh it from its webhook on each occurrence" to
  additionally have each occurrence refresh that document from its
  configured webhook, the same as clicking its own "Refresh from
  webhook" button, just on a schedule instead of on demand -- only
  takes effect for a document that actually has a webhook configured.

An existing entry's edit page also has a Delete button, with a
confirmation prompt. Both come back to wherever you opened the form
from -- the main Calendar screen, or a document's own Calendar tab.

### Import

A single-field form: pick an `.ics` file and import it. Import is
best-effort: `SUMMARY`, `DESCRIPTION`, `DTSTART`, and `RRULE` are read
(a yearly rule becomes Annually; a monthly rule with a 3- or 6-month
interval becomes Quarterly or Every 6 months); anything else in the
file is ignored. After a successful import, the page reports how many
entries were created.

## Assets

The asset registry, reached from Assets in the sidebar (submenu: All
Assets, By Type, which expands to one entry per asset type defined for
the tenant, Custom Fields, Export, Import).

### Asset list

A table of every asset (Name, Type, External ID, Status) with a
type-based filter dropdown at the top, an Edit link and a Delete button
(with confirmation) per row, and a "+ New asset" button.

### New / edit asset

Fields:

- Name (required).
- Asset type: picking a different type here dynamically swaps which
  custom fields appear further down the form.
- External ID (optional): a serial number, asset tag, or cloud
  resource ID; also what an Event Promotion Policy's "Auto-link asset
  by" matches against when auto-linking an asset to a ticket.
- Status: active, in_repair, retired, or decommissioned.
- Whatever custom fields are defined for the selected type (see Custom
  Fields below), each rendered as the appropriate input for its field
  type.

Editing an existing asset also shows an "Export to PDF" button, the
document links for that asset with the same inline "Add link" control
tickets have, and a read-only "Linked Tickets" table listing every
ticket whose Asset field points at this one.

### Custom Fields

Reached from Assets > Custom Fields (or, in the Admin nav, under Admin
> Tenant Administration > Asset Types, since defining the asset schema
itself is treated as an admin task rather than day-to-day asset work).
A table of every custom field defined for the tenant, showing which
asset type it applies to (or "All types"), its key, label, field type,
and whether it's required. "+ New custom field" opens a form:

- Applies to: a specific asset type, or "All types" to attach the field
  to every type at once.
- Key: the internal, lowercase identifier stored on each asset.
- Label: the human-readable name shown on forms.
- Field type: Text, Number, Yes/No, Date, URL, Email, or Select.
- Select options (comma-separated): only used when Field type is
  Select.
- Required: whether the field must be filled in when creating or
  editing an asset of that type.

### Asset Types

Also reached from Admin > Tenant Administration > Asset Types (the
former Assets > Asset Types menu entry moved there, since it's schema
definition rather than day-to-day use). A table of every asset type
(Key, Name, number of custom fields attached, Active/inactive) with a
"+ New asset type" form asking for a Key, Name, an optional icon name,
and an optional description. Deleting a type also deletes every asset
of that type, and the confirmation prompt says so.

### Import

A three-step flow. First, Assets > Import: pick the asset type the
imported rows belong to, the file format (CSV, or JSON as an array of
objects), and the file itself. Second, a column-mapping screen: for
every target field (built-in fields plus that type's custom fields),
pick which column in your file feeds it, or leave it on "-" to skip it;
RAIN suggests a mapping automatically based on matching header names.
Third, after committing, a result screen reporting how many rows were
created versus updated (existing assets are matched and updated by
External ID; anything without a matching External ID is created new)
and listing any per-row errors.

### Export

Assets > Export. Pick an asset type (this determines which custom
fields are available as columns; leaving it on "All types" limits you
to the built-in columns), then the same column table used by every
other export screen in RAIN: a checkbox, the source field, an editable
header, and a numeric order, plus a format choice (CSV, JSON, or
Excel) and an optional name to save the layout as a reusable profile.
Saved profiles for this screen remember which asset type they were
built for.

## Documents

The document repository, reached from Documents in the sidebar
(submenu: All Documents, Upload).

### Document list

A table of every document (Number, Title, Tags, File, Uploaded date)
with a search box that matches against title, document number
(`DOC-000123`), or a tag, and an "+ Upload document" button.

### New document

Despite the button being labeled "Upload document", this screen offers
two ways to create one, switched with a tab control:

- Upload a file: pick any file from your computer, up to 25MB.
- Type new content: choose to save it as plain text (`.txt`) or
  Markdown (`.md`), then type the content directly into a textarea.
  This is how you create a placeholder document with nothing to upload
  yet, just a title and some notes.

Either way, Title (required), Description (optional), and Tags
(optional, comma-separated) are entered once at the top of the form and
apply regardless of which tab you use. If you arrived here from another
record's "link a document" action, the new document is attached to that
record automatically and the page says so.

### Document detail

Above the tabs, next to the header, tags show as badges with a pencil
icon to edit them (comma-separated, same as on upload) -- "No tags."
if none are set yet. Below that, a "Shareable in the client portal"
checkbox: on, this document appears in the [Client Portal](#client-portal)'s
Shareable documents tab for every visitor, including one with no
account at all, regardless of that tenant's require-sign-in setting --
off by default, so nothing is exposed until you opt it in here. Below
that, the page is split into tabs:

- Description: a plain textarea, saved independently of the file
  itself.
- Contents (only shown for `.txt`/`.md` files): an inline editor. For
  Markdown files, a further Write/Preview tab pair lets you render the
  current text through the same Markdown renderer used by "Export to
  PDF", so what you preview is what the PDF will actually look like.
  Saving diffs what you typed against what's actually stored -- opening
  the editor and saving with nothing really changed (including a save
  that only differs by a trailing blank line) doesn't count as a
  change, so it never raises the alert below on its own.
- Auto-update (only shown for `.txt`/`.md` files): pick a webhook
  definition to populate this document's contents from, and optionally
  check "Emit syslog alert on change" to raise a syslog event (which
  Event Promotion Policies can turn into a ticket) whenever the stored
  content actually changes -- either from a webhook refresh below, or
  from a manual save on the Contents tab above; both go through the
  same diff. The event's detail includes a compact diff (added/removed
  lines) of exactly what changed, viewable in the live syslog viewer or
  on whatever ticket it promotes to. A "Refresh from webhook" button
  appears once a webhook is set, along with the timestamp of the last
  refresh; each refresh diffs the new response against what's stored,
  so nothing changes (or alerts) if the source hasn't.
- Links: every ticket or asset this document is linked to, each with
  an Unlink button, and an "Add link" control below the table. Pick
  Ticket or Asset with the pill selector, then either a ticket number
  (`INC-000123`) or a numeric asset ID, and click "Add link".
- Calendar: every calendar entry tied to this document (Title, Date,
  Repeats, and an "auto-refresh" badge on any that also refresh this
  document's content on occurrence -- see Calendar above), each with
  Edit and Delete, and a "+ New reminder" button that opens the
  calendar entry form pre-filled for this document and returns you
  here afterward.

The page header itself shows the document's filename and size, its
upload date, and three actions: Download, Export to PDF (which notes
the source webhook and last refresh date if the document is
webhook-populated), and Delete (with confirmation, and this cannot be
undone).

## Search results

Reached by typing anything other than an exact record number into the
topbar search bar. Shows a ranked table of matching tickets and
documents (a Type badge, the record number, and the title with a
highlighted snippet of the matching text) -- a document can match on
its tags as well as its title/description, and the snippet reflects
whichever one matched. A "no matches" message shows if nothing was
found; leaving the search box empty shows a prompt instead of an empty
results table.

## Client Portal

A separate, tenant-specific page at `/portal/<tenant slug>` for filing a
request without navigating the full app -- no sidebar or topbar, just
this page. Every visitor, signed in or not, sees a tabbed layout:

- **Request Something** (shown first/active by default): the same
  [Service Catalog](#service-catalog) the main app's Records Authority
  menu has, for requesting a service without navigating there.
- **Report Something**: the incident report form (what you need, what's
  happening, details, criticality, a "New ticket" button) and "Tickets
  reported by me," which only lists anything once you've signed in.

Both tabs accept a submission with or without a session -- gated by
this tenant's own `portal_require_auth` setting (see below), not by
whether you happen to be signed in; a request filed with no session
records "an unauthenticated user" as its reporter, same as an anonymous
incident always has.

**Signed in** additionally gets a search bar and two more tabs:

- **Pending Actions**: tickets currently waiting on your decision --
  same list as clicking through to each one's own Approval card would
  show.
- **Document Archive**: every document in the tenant's repository,
  linking out to each one's own page.

Report Something's ticket table also gains an Escalate button per
ticket, once signed in, if your tenant has an escalation webhook
configured.

Clicking a ticket number in that table opens a lightweight timeline
view instead of navigating away -- just what's changed and when
(status changes, comments, assignment/asset changes, approval
decisions), newest- or oldest-first, the same activity feed the full
ticket page shows but without any of its editing controls. An "Edit
ticket" button at the bottom opens the real, full ticket page
(requires signing in, same as ever) for anyone who wants to comment,
reassign, or change status.

**Today's events**, above the tabs, lists anything due on the tenant
calendar today (recurring or one-time), or "None" if nothing is. Shown
to every visitor regardless of sign-in status.

**Shareable documents** (only shown once at least one exists): a tab
listing every document marked "Shareable in the client portal" from its
own page (see [Document detail](#document-detail)). This tab is
reachable by *every* visitor, including one with no account at all --
even on a tenant with "Require sign-in" (below) turned on. In that
case, an anonymous visitor lands on a stripped-down version of this page
showing only this tab (nothing else the portal normally offers is
reachable without signing in); with require-sign-in off, or once
you're signed in, it just sits alongside the other tabs as usual. Its
name defaults to "Shareable documents" but is renamable per tenant
(e.g. "Trust Center") under Admin > Branding.

Four settings control this page, all under Admin > Branding > "Public
incident portal" (client_admin can reach this section for their own
tenant; internal_admin needs to switch to a tenant first):

- **Require sign-in**: on, only signed-in users of this tenant can file
  through the portal; off, anyone with the link can, and the ticket
  records "an unauthenticated user" as the reporter. Shareable documents
  (above) are reachable either way.
- **Show instance branding**: on, the portal shows this instance's
  logo/name/accent color, same as every signed-in page; off, a plain,
  unaccented page showing only the tenant's own name -- for a portal
  shared outside your own organization.
- **Escalation webhook**: which of this tenant's configured webhooks
  (Admin > Webhooks) the Escalate button calls, on the ticket detail
  page and here. Leave unset and no Escalate button shows anywhere for
  this tenant.
- **Shareable documents tab name**: what the tab above is labeled;
  defaults to "Shareable documents."

A signed-in visitor of a *different* tenant than the one in the URL is
always turned away with a 403, regardless of the require-sign-in
setting -- that setting controls whether an account is required at
all, not whether an account for the wrong tenant is accepted.

## Roles and permissions

RAIN has three roles, assigned per user under Admin > Users:

- Internal Admin: platform-wide. Can manage every tenant, switch which
  tenant they're actively viewing, and reach every screen under Admin >
  Platform Administration.
- Client Admin: full admin rights, but pinned to one tenant. Reaches
  every screen under Admin > Tenant Administration for that one tenant,
  but never Platform Administration and never another tenant's data.
- Client: a regular user of one tenant, with no admin screens at all.

Client and Client Admin accounts both require a tenant to be selected
when the account is created or edited; Internal Admin accounts don't
belong to any single tenant.

## Admin

The Admin section (sidebar: Admin) is only visible to Internal Admin
and Client Admin users, and is itself split into two submenus that
match that split in permissions.

### Platform Administration

Visible only to Internal Admin users. Covers everything that spans
every tenant or applies instance-wide.

**Branding.** Instance name, accent color (a color picker), font
(a dropdown of system/web-safe fonts, since nothing is downloaded from
a CDN), and an optional product logo (PNG, JPEG, SVG, or WebP, up to
5MB; leaving the file field empty on a later edit keeps the current
logo). Changes apply immediately across every tenant.

**Tenants.** A table of every tenant (Name, Slug, its database schema
name, Active/inactive), a "+ New tenant" form (Name and Slug), and, for
each tenant, a "Switch to" button that changes which tenant's data an
Internal Admin is currently viewing everywhere else in the app.

**Auth Providers.** A table of the three provider types: Local (always
enabled, no configuration needed), LDAP, and SAML, each showing whether
it's enabled and, if applicable, when it last synced. LDAP and SAML
each have their own Configure page:

- LDAP: connect one directory server. Fields cover the connection
  (Server URI, StartTLS checkbox, Bind DN, Bind password), user sync
  (User base DN, User filter, Email attribute, Display name attribute),
  group sync (Group base DN, Group filter, Group name attribute, Group
  member attribute), and target and schedule (which tenant every
  synced user and group lands in, as role Client, and how often the
  sync runs in minutes). A status card at the top shows the last sync
  time and summary, with "Test connection" and "Sync now" buttons.
  Synced users never get a local password; every login for them binds
  live against the directory instead. Only one directory can be
  configured, syncing into exactly one tenant.
- SAML: configure SAML 2.0 single sign-on against one identity
  provider. The page first shows this RAIN instance's own SP metadata
  URL and ACS URL for you to give to the IdP. The form itself covers
  the Identity Provider (entity ID, SSO URL, and its X.509 signing
  certificate), the Service Provider (this instance's entity ID),
  attribute mapping (which assertion attributes carry username, email,
  first name, last name, and role, plus which exact role-attribute
  value grants Internal Admin, case-sensitive; any other value, or a
  missing attribute, grants Client instead), and a target tenant that
  every SAML-provisioned user other than an Internal Admin lands in. A
  first-time sign-in creates the user; an email that already belongs to
  a local or LDAP account is refused rather than silently taken over.
  Every sign-in after the first refreshes that user's name and role
  from the assertion. Only one identity provider can be configured,
  signing into exactly one tenant.

**SMTP Relay.** One outbound mail relay for the whole instance: Host,
Port, From address, Username, Password (leave blank on edit to keep
the current one), and a "Use STARTTLS" checkbox. Who actually receives
ticket notifications is configured per tenant, separately, under
Notification Channels.

**Syslog Listener.** Shows whether the built-in listener is up, and
which port it's listening on for TCP and UDP. An "Untreated event
retention" card sets, in hours, how long an event that never gets
promoted into a ticket is kept before being discarded (0.5 hour
minimum; 12 hours by default); this never applies to an event that was
promoted, since its ticket keeps that link valid regardless of age. A
routing rules table below lets you map incoming events to tenants (or
discard them outright) by matching host or program against a pattern,
with "+ New routing rule" opening a form for Action (route to tenant,
or discard), Tenant (when routing), Match on (host, program, or
message), Pattern, an optional Regex checkbox for treating the pattern
as a regular expression instead of a plain substring, and Order. The
first matching rule wins; an event matching nothing is dropped.

**Users.** A table of every user across every tenant (Name, Email,
Role, Tenant, Auth source, Active/disabled) with a Deactivate button
per active row, an Edit link, and a "+ New user" form (Full name,
Email, Password, Role, and Tenant, the last required for Client and
Client Admin roles). Editing a user lets you change their name, role,
tenant, and, for local accounts, reset their password by typing a new
one (leave blank to keep the current one) or deactivate them via an
Active checkbox. LDAP-sourced users show their bind DN instead of a
password field, since sync overwrites their name, tenant, and active
status on every run; their role is not touched by sync, so a manual
role change here sticks.

**API Documentation.** A Swagger UI listing every route the web app
itself exposes, grouped by area (Tickets, Assets, Admin, Portal, ...),
for reference -- there's no separate API key or token to request,
since this documents the same server-rendered routes the UI already
calls rather than a distinct integration API. To react to RAIN's events
from outside the app, use Webhooks and Platform Response Rules instead.

### Tenant Administration

Reachable by both Internal Admin (for whichever tenant is currently
active) and Client Admin (for their one tenant). Covers everything
scoped to a single tenant's own configuration.

**Groups.** Named sets of users, used as an approval flow step's
target so a step can say "anyone on this team" instead of naming
people individually. The list shows Name, Description, member count,
and Source (local or LDAP, for a group synced in automatically). "+ New
group" asks for a Name and an optional Description. Opening a group
shows its member list with a Remove button per member and a
type-to-search "Add member" control. An LDAP-sourced group's page notes
that membership is overwritten on every sync run to match the
directory, so a manual add or remove there only lasts until the next
sync.

**Ticket Statuses.** The tenant's own set of statuses tickets can move
through, replacing a fixed open/closed enum. The table shows Order,
Status (as its colored pill), Key, whether it counts as "closed" (which
stamps a closed date on a ticket moved there), and an active toggle.
"+ New status" asks for a Label, a Key, a Color (color picker), a
"Counts as closed" checkbox, and an Order. Deactivating a status hides
it from new selections without affecting tickets already set to it;
deleting one behaves the same way. (The "Root cause assistance"
automation toggle lives under Platform Response Rules, below, not
here -- it reacts to a ticket closing, the same as every other rule on
that screen, rather than being a property of the statuses themselves.)

**Notification Channels.** Named destinations a Platform Response Rule
can notify. Each channel has a Type (email, Slack, or webhook) and a
Name. The fields below that depend on the type: email asks for a
comma-separated list of Recipients; Slack asks for an incoming webhook
URL; webhook asks you to pick one of the tenant's existing webhook
definitions (Admin > Webhooks) rather than entering a URL a fourth
place. Email and Slack channels also expose an editable Message (and,
for email, a separate Subject), pre-filled with a sensible default if
left blank, supporting placeholders `{{ticket_number}}`, `{{title}}`,
`{{description}}`, `{{severity}}`, `{{status}}`, and `{{ticket_type}}`
that get substituted with the actual ticket's values whenever a
Platform Response Rule sends through that channel.

**Approval Flows.** Named, ordered approval processes that a change
ticket attaches to. The list shows each flow's steps in order (label
and who's assigned), a "syslog on approval" badge when that's turned
on (below), and which flow, if any, is marked default (used to
pre-select on new change tickets); a "Make default" button switches
it. Creating or editing a flow gives you a Flow name, a "Make this the
default flow" checkbox, an "Emit a Syslog event when a Change running
this flow is fully approved" checkbox (off by default), and a variable
number of steps (use "+ Add step" / "Remove" to resize), each with a
Label, a Group, and an individual user (via type-to-search); a step
needs one or the other, and if both are filled in, the group wins. A
step doesn't open for decisions until the one before it clears. When
the syslog checkbox is on, the moment the last step clears a change
running that flow fires a synthetic syslog event (the same mechanism a
document's "alert on change," below, uses) -- visible in the live
syslog viewer and eligible to match Event Promotion Policies, same as a
real inbound line.

**Service Catalog.** The list shows each service's Name, Key (its URL), what it Produces
(incident/vulnerability/change), payload Format, Approval flow (if any),
question count, and an active toggle. "+ New service" gives you:

- **Name**, **Key** (used in its URL, e.g. `provision-user`),
  **Description** (shown on the catalog list), whether it's **Active**.
- **Produces** (which ticket type a submission creates), **Severity**
  (fixed for every submission -- the requester doesn't choose it), and
  **Payload format** -- JSON or `key=value` lines, for how the submitted
  answers become the created ticket's description.
- **Requires approval** plus an **Approval flow** picker, reusing the
  same flows Change tickets use (see Approval Flows above) -- shown only
  once Produces is set to "Change" (an incident or vulnerability has no
  approval concept). A Change service must require approval, with a flow
  selected, to save at all -- same rule the manual New Ticket form
  enforces.
- **Questions, in order** -- up to 10, each with a **field_key** (also
  the name/key the produced ticket's payload uses for that answer), the
  **Question** text shown to the requester, a **Type** (Text, Number,
  Yes/No, Date, URL, Email, or Select), **Options** (comma-separated, for
  Select), and **Required**. Use "+ Add question" / "Remove" to resize
  the form from 0 to 10 questions.
- Optionally, a question's **Source document**: pick an existing
  document and a **Source mode** to pull its value from that document
  instead of (or as a starting point for) free-form entry --
  **Content** uses the whole document (each line becomes an option, for
  a Select question), **Regex** or **JSONPath** extract from it (a
  regex's first capturing group if it has one, else the whole match; a
  JSONPath's every result). A Select question gets every match/result as
  its option list; any other type gets the first one as a prefilled but
  still-editable default. Click **Preview** next to a question to check
  what a pattern currently resolves to before saving.

**Event Promotion Policies, Platform Response Rules.** Covered in full
under Automation above; the Admin menu links straight to the same pages
Tickets links to.

**Import Ticket Field Pack.** Bulk-defines ticket custom fields from an
uploaded spreadsheet instead of adding them one at a time -- see "Custom
Fields (tickets)" above for what a custom field is and where they show
up. Upload a CSV or Excel file whose header row names the fields you
want (a row or two of real/representative data underneath each column
lets it guess a field type -- text, number, boolean, date, URL, email,
or select -- automatically); a header-only file works too, everything
just starts as Text on the next screen, and nothing from the data rows
themselves is ever imported or stored, only the field definitions you
confirm are. The next screen lists every detected column with its
guessed key, label, and type, all editable, plus a preview of its
sample values, and an Include checkbox (unchecked by default for a
column whose key already exists); review and adjust before submitting.
The result screen shows how many fields were created and lists any
skipped (a duplicate key, or a missing key/label).

**Webhooks.** Centrally-defined outbound HTTP calls, reused by Platform
Response Rules, document auto-update, notification channels, and the
Escalate button (Admin > Branding picks which one), instead of entering
a URL separately in each of those. The list shows
Name, Method, URL, Timeout, and Success codes, with a "+ New webhook"
form covering: Name, HTTP Method (POST, GET, PUT, or PATCH), URL,
Timeout in seconds, Success codes (a comma-separated list of HTTP
status codes that count as success; anything else counts as a failed
call), Headers (one `Name: value` pair per line), a Payload template
(JSON, ignored for GET requests, since those have no body) using the
same double-brace placeholders as notification channels where the
caller supports them, and an "Emit syslog alert on failure" checkbox
(off by default) that raises a syslog event whenever a call using this
webhook fails or times out, wherever it's called from.

**Placeholders reference.** Two independent placeholder systems exist,
used in different template fields -- the wrong syntax in the wrong
field is left as literal, unsubstituted text rather than an error, so
it's worth knowing which is which:

- Double braces (`{{ticket_number}}`) -- a webhook's Payload template
  and a notification channel's Message/Subject template. Both fill in
  `{{ticket_number}}`, `{{ticket_type}}`, `{{title}}`, `{{description}}`,
  `{{severity}}`, and `{{status}}` from whichever ticket triggered the
  call: a Platform Response Rule's "Call a webhook"/"Notify Slack"/
  "Notify Email" action, or the ticket detail page's "Escalate" button.
  A document's "Refresh from webhook" (and the calendar's matching
  auto-update policy) calls with none of these -- a payload template
  used there should be static, since none of the placeholders resolve.
- Single braces (`{message}`) -- an Event Promotion Policy's Title
  template (plain Python string formatting, deliberately different from
  the double-brace syntax above, which would otherwise misparse a JSON
  payload's own braces). Every promotion type gets `{message}`,
  `{host}`, and `{program}` from the matching event; an ML anomaly
  policy also gets `{count}`, `{window}`, and `{score}`.

**Asset Types.** Covered under Assets above; reached from here since
defining the asset schema is treated as an admin task.
