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
numbers, ranked by relevance, and takes you to a results page listing
matches with a highlighted snippet of where the match occurred.

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
- A three-dot row menu on every ticket with: Mark closed, Mark/Unmark
  problematic, Promote to Change (incidents and vulnerabilities only),
  Mark cancelled (changes only), and Get a hard copy (PDF).

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

### Ticket detail

The single-ticket page. At the top is a status stepper: one button per
tenant-defined status, with the current one highlighted; clicking any
other status moves the ticket there immediately. Next to it are
quick actions: "Promote to Change" (incidents/vulnerabilities only),
"Mark problematic" / "Unmark problematic", and "Export to PDF".

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
  which Event Promotion Policy or Correlation Rule auto-created it),
  Source event (the originating syslog event ID, or "manually
  created"), Promoted from (if this ticket was promoted from another
  one, a link back to it), Change window (start and end date/time, on
  change tickets only), and Created (timestamp).
- The document links list for this ticket (see Documents below for how
  linking works) with an inline "Add link" control.

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
edit, every approval decision, every document link/unlink, and every
Platform Response Rule that fired because of this ticket, each entry
naming who or what caused it and when.

### Events (live feed)

The live view of the syslog listener's incoming stream, at Records
Authority > Events. A status pill in the corner shows whether the feed
is connected, and a Pause button freezes it in place so you can read
without new events pushing the list around. Two filters narrow what's
shown: a free-text filter matched against host, program, and message,
and a minimum-severity dropdown (All / Info and up / Warning and up /
Error and up / Alert and up, using syslog severity levels).

Check the boxes next to one or more events to reveal a selection menu
with four bulk actions: "Turn these into incidents", "Turn these into
vulnerabilities", "Correlate these" (jumps to Correlation Rules with a
pattern pre-filled from the selection), and "Discard these". Events
that never get promoted into a ticket are dropped automatically after
the tenant's configured retention window regardless of whether you act
on them here.

### Export (tickets)

At Records Authority > Export. Filter which tickets to include by type
and status, pick an output format (CSV, JSON, or Excel), and choose
which columns to include, what header text each one gets, and what
order they appear in via a per-column table (a checkbox, the source
field name, an editable header, and a numeric order). Optionally save
the whole column layout under a name so you can re-run the same export
later without reconfiguring it; saved profiles appear in a list below
with a "Load" link.

## Automation

Three kinds of rules turn the raw syslog stream and ticket activity
into action. All three live under Admin > Tenant Administration,
though the first two are really about syslog events and the third is
about tickets.

### Event Promotion Policies

At Tickets > Rules (Admin > Tenant Administration > Event Promotion
Policies). A policy is a single regular expression checked against one
incoming syslog event; the first policy (in Order) whose pattern
matches wins, and that event becomes a new ticket. Each policy defines:

- Name.
- Ticket type to create: incident, vulnerability, or change.
- Severity to assign the new ticket.
- Match on: which event field the pattern is checked against, one of
  message, host, or program.
- Pattern: a regular expression.
- Order: lower numbers are evaluated first.
- Title template: the new ticket's title, with `{message}`, `{host}`,
  and `{program}` placeholders available.
- Auto-link asset by (optional): don't auto-link, or match the event's
  host or program against an asset's External ID field to link the new
  ticket to that asset automatically.

Each policy row has a small "Test" form: paste a sample log line in and
it reports whether the policy's current pattern would match it, without
creating anything.

### Correlation Rules

At Tickets > Correlation Rules. Where a promotion policy reacts to one
event, a correlation rule reacts across multiple events. The "New rule"
form splits into two tabs for the two ways a rule can decide that:

**Simple repetition** -- when enough events matching its pattern land
within a trailing time window, one ticket is created.

- Threshold (events): how many matching events must land within the
  window before a ticket is created.

**ML anomalies** -- an online model learns what this rule's traffic
normally looks like (from each matching event's severity, message
length, and time of day) and fires on an event that doesn't fit,
instead of a fixed count.

- Anomaly score threshold: how unusual (0-1, higher = more unusual) a
  new event's score must be to fire a ticket.
- Warm-up events: how many events the model sees before it's allowed to
  fire at all, so a brand new rule doesn't flag its own cold start as
  anomalous.

Fields shared by both, on top of the same
name/pattern/match-on/severity/ticket-type/order used by promotion
policies:

- Pattern: leave blank to consider every event; narrow it to scope
  either kind of rule to a slice of traffic first.
- Window (minutes): for Simple repetition, the trailing window the
  threshold is measured over; for ML anomalies, the cooldown before the
  same rule (and group) can fire again.
- Group by: none, host, or program. "None" correlates (or, for ML
  anomalies, trains) across every matching event tenant-wide as one;
  "host" or "program" gives each distinct value its own count/model
  and, if it fires, its own ticket.
- Title template, with `{count}`, `{window}`, `{message}`, `{host}`,
  and `{program}` placeholders (the last three come from the most
  recent contributing event), plus `{score}` for ML anomalies. Leave
  blank for a sensible default.
- Auto-link asset by, same as promotion policies but matched against
  the most recent contributing event.

Once a rule (or a rule and group, if grouped) fires, it re-arms only
after its window has elapsed, so a single burst of activity produces
one ticket, not one per event past the threshold. Each rule also has a
toggle button to enable or disable it without deleting it, and a "New
rule" form pre-fills the Simple repetition tab from whatever events you
had selected if you got here via Events' "Correlate these" action.

### Platform Response Rules

At Tickets > Platform Response Rules. These react after a ticket
already exists, regardless of whether it was promoted automatically or
created by hand. Unlike the previous two rule types, every active rule
whose pattern matches fires, not just the first, and each one can run
several actions.

The list page's "New rule" form only asks for the rule itself: name,
trigger (when an incident is created, when a vulnerability is created,
or when a change is created), match on (the new ticket's title or
description), pattern, and order. Saving takes you to that rule's own
detail page to add actions.

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

Every firing of a rule, and the outcome of each of its actions, is
logged both to that rule's own history and to the matching ticket's
Activity feed, whether or not the action itself succeeded, so a failed
Slack post never hides the fact that the rule matched.

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
- Auto-update: pick a document (only documents that already have a
  webhook configured show up in this list) and each occurrence
  refreshes it from that webhook automatically, the same as clicking
  that document's own "Refresh from webhook" button, just on a
  schedule instead of on demand.

An existing entry's edit page also has a Delete button, with a
confirmation prompt.

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
  resource ID; also what Event Promotion Policies and Correlation
  Rules match against when auto-linking an asset to a ticket.
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

A table of every document (Number, Title, File, Uploaded date) with a
search box that matches against title or document number
(`DOC-000123`), and an "+ Upload document" button.

### New document

Despite the button being labeled "Upload document", this screen offers
two ways to create one, switched with a tab control:

- Upload a file: pick any file from your computer, up to 25MB.
- Type new content: choose to save it as plain text (`.txt`) or
  Markdown (`.md`), then type the content directly into a textarea.
  This is how you create a placeholder document with nothing to upload
  yet, just a title and some notes.

Either way, Title (required) and Description (optional) are entered
once at the top of the form and apply regardless of which tab you use.
If you arrived here from another record's "link a document" action,
the new document is attached to that record automatically and the page
says so.

### Document detail

A single document's page, split into tabs:

- Description: a plain textarea, saved independently of the file
  itself.
- Contents (only shown for `.txt`/`.md` files): an inline editor. For
  Markdown files, a further Write/Preview tab pair lets you render the
  current text through the same Markdown renderer used by "Export to
  PDF", so what you preview is what the PDF will actually look like.
- Auto-update (only shown for `.txt`/`.md` files): pick a webhook
  definition to populate this document's contents from, and optionally
  check "Emit syslog alert on change" to raise a syslog event (which
  Event Promotion Policies can turn into a ticket) whenever a refresh
  actually changes the stored content. A "Refresh from webhook" button
  appears once a webhook is set, along with the timestamp of the last
  refresh; each refresh diffs the new response against what's stored,
  so nothing changes if the source hasn't.
- Links: every ticket or asset this document is linked to, each with
  an Unlink button, and an "Add link" control below the table. Pick
  Ticket or Asset with the pill selector, then either a ticket number
  (`INC-000123`) or a numeric asset ID, and click "Add link".

Above the tabs, the page header shows the document's filename and size,
its upload date, and three actions: Download, Export to PDF (which
notes the source webhook and last refresh date if the document is
webhook-populated), and Delete (with confirmation, and this cannot be
undone).

## Search results

Reached by typing anything other than an exact record number into the
topbar search bar. Shows a ranked table of matching tickets and
documents (a Type badge, the record number, and the title with a
highlighted snippet of the matching text), or a "no matches" message if
nothing was found. Leaving the search box empty shows a prompt instead
of an empty results table.

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
deleting one behaves the same way.

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
and who's assigned) and which flow, if any, is marked default (used to
pre-select on new change tickets); a "Make default" button switches
it. Creating or editing a flow gives you a Flow name, a "Make this the
default flow" checkbox, and a variable number of steps (use "+ Add
step" / "Remove" to resize), each with a Label, a Group, and an
individual user (via type-to-search); a step needs one or the other,
and if both are filled in, the group wins. A step doesn't open for
decisions until the one before it clears.

**Event Promotion Policies, Correlation Rules, Platform Response
Rules.** Covered in full under Automation above; the Admin menu links
straight to the same pages Tickets links to.

**Webhooks.** Centrally-defined outbound HTTP calls, reused by Platform
Response Rules, document auto-update, and notification channels,
instead of entering a URL separately in each of those. The list shows
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

**Asset Types.** Covered under Assets above; reached from here since
defining the asset schema is treated as an admin task.
