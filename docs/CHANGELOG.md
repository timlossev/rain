# Changelog

What's shipped in RAIN, in the order it shipped. Grouped by date rather
than a version number -- there's no release/tag scheme yet, so a date is
the honest anchor point. Each entry is a synthesis of that day's commits,
not a 1:1 commit dump; see `git log` for the literal history this is
drawn from. Updated alongside every push to `main`.

## 2026-08-31

- **Performance**: Home's "Refresh when rendering" now calls every
  flagged document's webhook concurrently instead of one at a time --
  with several slow webhooks flagged, a page load used to wait out
  each one's full timeout in sequence; now it waits out roughly the
  slowest one, once. The database side of a refresh (diff/save/commit)
  still happens sequentially per document, since it shares one
  connection -- only the network round-trips run in parallel. The
  single-document callers (the manual "Refresh from webhook" button,
  the calendar sweep) are unchanged.

- **Refresh from webhook on view**: a new checkbox in a document's
  Properties tab ("Refresh from webhook every time this page is
  viewed") re-runs the document's configured webhook every time its
  page is opened, not just on the manual "Refresh from webhook"
  button. A successful call shows (and saves) the fresh content; a
  failed one shows a small notice and falls back to the last saved
  version instead of an error page. Also fixed: the document detail
  page never actually rendered the failure message the manual refresh
  button's redirect already carried in its `?error=` query param.
- That checkbox is now labeled "Refresh when rendering" and also covers
  Home: a document flagged both "Refresh when rendering" and "Show on
  landing page" gets a fresh webhook call on every Home load too, not
  just its own page. Home falls back silently on a failed call (no
  banner there, unlike the document's own page) -- one stale response
  among possibly several documents shown isn't worth flagging.
- A small "Last updated `<timestamp>`" label now shows wherever a
  document's content actually renders (its own Contents tab, and each
  entry on Home) -- the last successful webhook refresh if it's ever
  had one, otherwise when it was last saved.
- A ticket's clamped description preview ("Show more") now shows 20
  lines before truncating, up from 15.
- Ticket detail page: the main card (badges, title, description,
  metadata) now has a light accent-tinted background, distinguishing
  it from the plain Approval/Links/Activity cards below it. The title
  line also truncates later (~30 more characters) before ellipsis-ing.
- **Kanban board**: a new "Kanban" entry under Records Authority
  (`/tickets/kanban`) shows the same tickets and filters as the ticket
  list, grouped into one draggable column per status instead of table
  rows. Drag a card to a different column to move it there -- the same
  change the ticket's own status-stepper buttons make, reverted back
  to its original column if the move doesn't go through. Each card
  carries the same three-dot row menu as the table view. Capped at the
  first 500 matching tickets (with a banner if that's hit); the
  filter bar itself moved into a shared partial (`tickets/
  _filter_bar.html`) so the table and board views can't drift apart on
  what filters mean.
- Home's "Last updated" label is now a pill ("Version from
  `<timestamp>`") next to each document's title, instead of a plain
  line above its content. Ticket detail page: the accent tint moved
  off the whole card and onto just the description box, which now
  also gets a full border so it's clear where it ends and the
  metadata table below it begins -- previously the whole card
  (badges/title/metadata included) was tinted.
- New "Prioritized" filter chip (table view and Kanban board), next to
  Mine/Unassigned/Problematic -- shows only the two highest severities
  (currently "high" and "critical").
- Kanban card: the ticket number is now its own pill/link, separate
  from the title -- previously folded into the title text ("INC-000123:
  Some title").
- **Row-spacing switch** on the ticket list: a Normal/Condensed toggle
  (persisted per browser) that tightens row padding so more tickets
  fit on screen -- display only, doesn't change how many tickets are
  fetched or paginated.
- **Tenant-configurable page size**: a new "Record list page size"
  setting under Admin > Branding > Tenant defaults (10/25/50/100/200,
  default 25) now backs every tenant-scoped record list in the app --
  Tickets, Assets, Documents, and this tenant's own admin config lists
  (Ticket Statuses, Webhooks, Groups, Approval Flows, Notification
  Channels, Custom Fields, Event Promotion Policies, Platform Response
  Rules). Deliberately doesn't apply to the handful of platform-level
  lists (Admin > Tenants, platform Users, Syslog Sources), which
  aren't any one tenant's records to have a page-size opinion about.
- Document Properties tab: "Refresh when rendering" moved to the
  Auto-update tab, next to the webhook it actually governs (it never
  belonged under Properties). "Uploaded" is now a pill on the right of
  its row instead of a plain line below the label, matching Home's own
  document pill. Fixed the tag editor's input overlapping its Save/
  Cancel buttons (it had no layout rule of its own at all).

## 2026-08-30

- **New landing page** (`/home`, and what signing in now lands on
  instead of Records Authority): a plain "Welcome to `<instance>`" by
  default, or -- once at least one document is flagged "Show on
  landing page" from its own Properties tab -- that document's own
  content instead (rendered Markdown, or plain text), stacked in title
  order if more than one is flagged. New top-level sidebar entry
  ("Home"), ahead of Records Authority.
- Client portal's "Today's events" now caps at 5, with a "+N more" link
  to the full calendar when there are more -- previously showed every
  due entry with no limit.
- Home page: welcome message is now centered and bold in the middle of
  the page instead of a small heading; the landing-page-document hint
  moved from a visible paragraph to the page's `?` help text. Home's
  sidebar entry now matches the bold weight of its sibling categories.
- Docker build hardening: both build stages now run `apk upgrade
  --no-cache` before installing anything, so the image's system OpenSSL
  (and every other Alpine package) is pulled forward to whatever the
  Alpine index has at build time regardless of how stale the floating
  `python:3.12-alpine` tag's cached layers are -- closes the Aug 2026
  OpenSSL advisory batch (CVE-2026-54874, 63072, 63075, 63076, 18798,
  14457). Documented that the existing `pip>=26.1.2` floor already
  covers CVE-2026-6357 and CVE-2026-13346 (both fixed at pip 26.1), and
  that `cryptography`'s vendored OpenSSL self-updates on the next build
  after pyca ships a release with the patched copy (no lockfile pins a
  stale resolved version).

## 2026-08-27

- **ML anomaly training status is now visible**: an ML anomaly policy
  (or a Repetition one with "Also flag statistically unusual
  occurrences" on) shows a compact badge on the policy list -- "No
  events yet", "115/250 training", "Live", or a mixed summary for a
  policy grouped by host/program -- and a full per-group breakdown on
  its own edit page, comparing events seen so far against the policy's
  Warm-up events setting.
- **Event Promotion Policies producing a change** can now name which
  approval flow to attach automatically (instead of always filing an
  unprotected change), and default that ticket's implementation window
  to starting the moment it's created with a 24-hour turnaround --
  editable afterward on the ticket, same as a manually-created one.
- **"Analyze root cause" now opens a preview window instead of posting
  straight to the ticket**: findings show up in a small modal first,
  with "Post as a comment" (submits it, same as the old direct-post
  behavior), "Copy to clipboard", or "Close" to discard it. Also added
  to the tickets list row menu, and made that whole menu correlate with
  the ticket detail page's own top-right button row -- Watch/Stop
  watching and Escalate joined it too, under the same conditions
  (Escalate only once a tenant has an escalation webhook; Watch showing
  the right state per row via one bulk query, not one per row).
- Sidebar logo/instance-name row and the topbar (breadcrumb/search/user
  menu) now share a height and vertical centering (`--topbar-height`),
  so they read as one continuous band across the top of the page
  instead of landing at two slightly different heights. The logo is
  also properly centered in the collapsed (icons-only) sidebar now,
  instead of hugging the left edge of that narrower column.
- **Two new Platform Response Rule triggers**: "When an incident/
  vulnerability/change is closed" (any status flagged "closed") and
  "When a change is fully approved" (its last approval step clearing),
  alongside the existing three "created" triggers -- same rule shape
  (pattern match, any number of actions) either way, just a different
  moment in a ticket's life to react to.
- Tickets list: "Mine" and "Unassigned" now un-toggle themselves on a
  second click, same as "Problematic" already did, instead of needing
  a separate "All" link (removed) to clear the assignee filter.
- Moved the "Root cause assistance" auto-analyze-at-closure toggle from
  Admin > Ticket Statuses to Tickets > Platform Response Rules -- it
  reacts to a ticket event (closure), the same as every rule on that
  screen, not a property of the statuses themselves.
- Record-type filter pills (Tickets list) all use the tenant's accent
  color when active now, instead of Incidents/Vulnerabilities getting a
  fixed red/orange while Changes got the accent -- that read as if
  incidents/vulnerabilities outranked changes in severity by type
  alone, which isn't what the color was meant to convey (severity is
  what the badges on the ticket itself are for).
- A round of small layout fixes: Admin > Branding's two cards now sit
  side by side on a wide screen instead of stacking in one narrow,
  individually width-capped column (new `.two-col-cards` utility, also
  usable elsewhere); the "Open incident portal" link moved off the
  topbar's tenant-name badge (now a plain label, not a link) into the
  user menu, next to Sign out, matching how the client portal's own
  "Back to full app" link already works; the sidebar's top-level accent
  color (below) uses a lightened `--accent-on-dark` derived color
  instead of the raw tenant accent, so a dark tenant-chosen accent
  doesn't read poorly against the sidebar's near-black background;
  `flex:0 0 Npx` and the "align a checkbox next to a labeled field"
  `margin-top:30px` -- both hand-typed the same way in a couple dozen
  places -- are now utility classes (`.field-w90/100/140/160`,
  `.field-narrow`, `.field-align-checkbox`), applied wherever they
  already matched exactly. Event Promotion Policies' "Test policy"
  dialog is one shared modal now, populated by whichever row's Test
  button was clicked, instead of one hidden modal per policy; and its
  "Promotion type" section (tabs, the ML sidecar checkbox, the shared
  algorithm field) is a single partial reused by both the list page's
  "New policy" modal and the Edit Policy screen, instead of two
  hand-kept-in-sync copies.
- Sidebar top-level categories (Records Authority, Assets, Documents,
  Calendar, Admin) now render in the tenant's own accent color instead
  of the flat sidebar palette every nested item uses, so the sidebar
  reads as a handful of sections rather than one long list. Nested
  sub-groups (e.g. Platform Administration under Admin) and leaf links
  are unaffected. Also fixed the sidebar search's result label, which
  read "Option in Quick Navigation (Tenant Administration)" -- naming
  its own search box instead of the category a result actually lives
  in -- to just "Option in Tenant Administration."
- **Repetition policies also flag anomalies, by default**: a
  "Repetition" Event Promotion Policy no longer needs a second,
  separate "ML anomaly" policy (with a duplicated pattern) just to get
  an anomaly signal on the same events -- an "Also flag statistically
  unusual occurrences" checkbox, on by default, runs the same anomaly
  scoring inline, at its standard settings, and notes an unusual
  occurrence as a comment on whichever ticket repetition already
  touched instead of spawning a second ticket. Repetition and anomaly
  detection were never really competing concerns; they just looked
  that way as two of three mutually-exclusive tabs on the policy form.
  Only the algorithm choice is surfaced on Repetition's own tab; the
  rest (group by, cooldown, threshold, warm-up) stays reachable from
  the ML anomaly tab if it's ever worth changing from the default,
  deliberately not duplicated onto Repetition's simpler tab.
- **Root cause assistance for tickets**: an "Analyze root cause" button
  on any ticket (and an opt-in "run automatically when a ticket closes"
  toggle, off by default, under Admin > Ticket Statuses) posts a
  comment summarizing two honest, non-causal signals -- a repeat-
  occurrence pattern (host/program distribution and time span across
  every syslog event promoted into the ticket) and similar past
  *closed* tickets (the existing full-text search, ranked). This is
  statistical/historical pattern-matching, not causal reasoning --
  nothing in the app (or `river`, its only ML dependency) determines
  *why* something happened, and the comment says so.
- **Selectable ML anomaly detection algorithm**: an Event Promotion
  Policy using "ML anomaly" now picks which `river.anomaly` detector
  it runs -- Half-Space Trees (the previous, still-default, hardcoded
  choice), Local Outlier Factor, or One-Class SVM -- each with a plain-
  language explanation of what it's better at, shown on the policy
  form. A firing ticket's description also now names the single most-
  deviated feature (severity, message length, or time of day) and how
  many standard deviations off this group's own history it was,
  computed from a running per-feature mean/variance (Welford's online
  algorithm) kept alongside the model.
- **Shareable documents / "Trust Center"**: a document can be marked
  "Shareable in the client portal," which exposes it through a new
  portal tab -- reachable by literally every visitor, including one
  with no account at all, even on a tenant that otherwise requires
  sign-in for the rest of the portal (`portal_require_auth`). The tab
  only appears once a tenant has at least one shareable document, and
  its label is renamable on Admin > Branding (e.g. "Trust Center").
- Swept the UI for em dashes and `--`, replacing them with a plain `-`
  -- an explicit style preference, not a functional change.
- Moved a document's tags, sharing checkbox, and upload date into its
  "Properties" tab (renamed from "Description," which now also lives
  there) instead of sitting above the tabs.
- Paginated the client portal's Document Archive and Shareable
  documents tabs -- previously unbounded, same issue "Tickets reported
  by me" had. `_pagination.html`'s macro now takes an optional `param`
  so more than one paginated list can share a page without one's Next/
  Prev resetting the other's.
- Event Promotion Policies: the pattern tester used to sit permanently
  under every single policy row (two extra table rows each, whether or
  not anyone was testing anything); it's now an on-demand "Test" button
  opening a small modal, same pattern the rest of the app already uses
  for a per-row action. Also fixed a missing gap between the ML
  anomaly algorithm's description text and the "Group by" dropdown
  below it (on both the list page's "New policy" modal and the Edit
  Policy screen), and combined "Auto-link asset by" and "Active" onto
  one row on the Edit Policy screen.

## 2026-08-25

- **Document tags**: optional, freeform, comma-separated tags on a
  document (Documents list, upload form, and an inline-editable badge
  row on the document's own page), folded into the same Postgres
  full-text index tickets/documents already use -- searchable from the
  global search bar and the Documents list's own search box, no
  separate tag index or screen. Hit (and worked around) a real Postgres
  constraint along the way: neither `array_to_string()` nor a plain
  array-to-text cast qualifies as `IMMUTABLE`, which a `GENERATED`
  column's expression requires -- a tiny per-tenant-schema `IMMUTABLE`
  SQL wrapper function does.
- **Calendar reminders for documents**: a document's own Calendar tab
  lists calendar entries tied to it via a new, plain
  `CalendarEntry.document_id` link, with a "+ New reminder" action --
  e.g. "this document is due for revision every quarter," independent
  of (but optionally combinable with, via one unified picker) the
  existing webhook auto-refresh-on-occurrence policy. Existing
  auto-refresh entries get backfilled onto their document's Calendar
  tab automatically.
- Replaced the plain `<select>` document pickers on the new calendar
  entry form and a Platform Response Rule's "Attach document" action
  with the same type-to-search picker already used to link a document
  to a ticket -- a `<select>` listing every document doesn't scale past
  a few dozen. Also tightened the calendar entry form's layout into
  grouped sections with less prose per field, and fixed the Syslog
  bridge section's checkbox sitting on a different line than the
  field next to it.
- Widened the event-preview modal (Events feed) and the document-
  preview modal (opened from a document ID anywhere it's linked) to
  the same larger size -- both show a full record's worth of content
  and read cramped at the old, generic modal width.
- Paginated the client portal's "Tickets reported by me" table --
  previously an unbounded list. `list_tickets_reported_by` couldn't
  reuse the shared `paginate()` helper as-is (that one's `.scalars()`
  call assumes a single-entity `select()`; this one also selects a
  computed "last update" column), so it does its own count + limit/
  offset instead.

## 2026-08-23

- **Unified Event Promotion Policies and Correlation Rules** into one
  system: a policy's `promotion_type` is now "single" (one event, one
  ticket -- the old TicketRule behavior), "repetition" (folds a repeat
  occurrence into an already-open ticket instead, marking it Problematic
  -- what `combine_by_title` used to do as a checkbox), or "ml_anomaly"
  (the online-model anomaly detection Correlation Rules used to own
  separately). Dropped Correlation Rules' "threshold" type outright --
  it duplicated what "repetition" already does more simply. One less
  admin screen, one less code path evaluating every event, and "New
  policy from selection" on the live event feed (renamed from
  "Correlate these") now lands on the same unified policy editor.
- **Custom attributes on tickets**: the same text/number/boolean/date/
  URL/email/select custom-field system the Asset Registry has, now
  extended to tickets -- tenant-wide across all three ticket types, no
  per-type scoping and no "Required" option (a ticket can be filed by
  automated paths -- Event Promotion Policies, the client portal,
  Service Catalog -- that don't know about custom fields at all). A
  default tenant schema still defines none; once a tenant adds some,
  they're capturable on the ticket form/detail page and importable/
  exportable right alongside the built-in columns. Also new: CSV/JSON
  import for tickets (create-only, incident/vulnerability -- a change
  needs an approval flow, which isn't something a spreadsheet column can
  express) -- ticketing had export but no import path before this.
- **Import Ticket Field Pack**: bulk-defines a tenant's ticket custom
  fields from an uploaded spreadsheet's header row instead of adding
  them one at a time -- sample data underneath each column is used to
  guess a field type (best-effort, always editable before saving);
  nothing from the sample rows themselves is imported or stored.
- **Portal background image**: an optional, instance-wide background
  image/wallpaper for the public client portal (Admin > Branding, next
  to the logo), shown only for a tenant with "Show instance branding"
  on. Unset by default -- the portal renders exactly as before until an
  internal_admin uploads one. Reuses the branding-logo's own S3/Postgres
  backup mechanism (`control.branding_assets`, one row per asset key),
  generalized to cover a second asset instead of just the logo.
- **Helm chart re-verification**: actually installed `helm` and ran
  `helm lint`/`helm template` across the documented deployment shapes
  (default, remote DB + S3 with a static key pair, remote DB + S3 on an
  IAM/instance-profile role, minimal mode) instead of just reading the
  YAML. Found and fixed two settings the app gained after the chart was
  first written that had never been wired into it: `ENABLE_PGVECTOR`
  (for a managed Postgres role that can't `CREATE EXTENSION`, or doesn't
  ship `vector` at all -- e.g. standard RDS in AWS GovCloud) and
  `RAIN_DOMAIN` (now also load-bearing for the password-reset-link Host-
  header fix above, not just Caddy's ACME cert request the way it is in
  the Compose deployment).
- Added this changelog, and a hook that reminds Claude Code to update it
  whenever new commits are pushed without touching it.

## 2026-08-22

- **Portal user menu**: a signed-in visitor to the client portal now
  gets the same identity info the authenticated app's topbar shows
  (name, role badge, schema build number, sign out), plus a portal-only
  "Back to full app" link -- previously there was no way to tell who you
  were signed in as, or get back to the real app, from the portal at
  all. Landed twice: first folded into the tab-switcher burger menu (to
  dodge a duplicate Sign-out button a rebase produced), then moved back
  out to its own top-right dropdown once that turned out to look broken
  next to the tabs instead of matching the rest of the app.
- **Branding logo durability**: the logo now backs itself up (S3 if
  `S3_BUCKET` is set, otherwise a new `control.branding_assets` Postgres
  table) and restores itself to local disk automatically at startup if
  the local copy is missing -- previously a container recreated with no
  persistent uploads volume (minimal mode, the single-container
  `docker run` quickstart) silently lost the logo until someone noticed
  and re-uploaded it.
- **Full-codebase security review**: three parallel audits (auth/
  session/crypto/RBAC, injection/input-handling, multi-tenancy/public
  surfaces), every finding independently re-verified against the real
  code before being trusted. Fixed:
  - Stored XSS -- Markdown document bodies were rendered to HTML with no
    sanitization and injected live via `innerHTML`/`|safe`; a crafted
    document could drive a same-origin request to mint a new
    `internal_admin` the moment anyone previewed it. Now sanitized
    through `bleach` with an explicit tag/attribute/protocol allowlist.
  - SSRF via webhooks -- a tenant admin's webhook URL had no host/scheme
    validation, and a Document's "refresh from webhook" wrote the raw
    response body into a tenant-readable document, making the platform's
    internal network (or a cloud metadata endpoint) readable through it.
    New `rain.core.url_safety.check_outbound_url`, enforced at call time
    for both webhooks and Slack notifications.
  - Blind SSRF via PDF export -- a document's `<img src="http://...">`
    made the PDF exporter itself fetch an attacker-chosen URL server-
    side. The link callback now refuses anything outside the two local
    prefixes it's actually meant to resolve.
  - Path traversal in the asset CSV/JSON import commit step -- its stash
    token was a raw, unvalidated form field.
  - CSV/Excel formula injection in ticket/asset exports, reachable from
    anonymous portal-filed ticket titles.
  - A password-reset email link built from the raw, unvalidated `Host`
    header (exploitable behind a load balancer with no `TrustedHost`
    equivalent in front).
  - Cross-tenant user-ID validation gap on ticket assignment/group
    membership/approval steps -- walking IDs could enumerate every
    tenant's user directory.
- **PDF export fixes**: long unbroken strings (a title, a URL, a token)
  wrapped instead of running off the page, and Unix newlines in document
  bodies/descriptions/comments rendered as real line breaks instead of
  one run-on line -- then the word-wrap fix was reverted after it turned
  out to crash *every* export whose content was long enough to need a
  page break, a genuine bug in xhtml2pdf's own error-reporting path (no
  newer release fixes it). Also caught and fixed a second regression
  from the SSRF fix above: it had silently blocked the logo's own
  legitimate embedding path (a `data:` URI for raster logos, a bare
  filesystem path for SVG ones), so every branded PDF export was
  quietly missing its logo until this was corrected.
- **Webhook SSRF guard relaxed**: the SSRF fix above was initially too
  strict -- it blocked any address that wasn't publicly routable,
  private/RFC1918 included, which broke real webhooks to internal
  targets (an on-prem Zabbix instance was the reported case). RAIN is
  explicitly built to run air-gapped; reaching a tenant's own internal
  network is the normal, intended use of a webhook here. Private
  addresses are allowed again -- loopback and link-local (which is what
  actually covers a cloud metadata endpoint) stay blocked, since neither
  is ever a legitimate webhook target in any deployment.
- Fixed document auto-update's JSON response handling and a row where
  the refresh timestamp ran into the next line with no space.
- README trimmed: cut implementation-depth asides that duplicated
  `docs/architecture.md` at a deeper level than a README needs, and
  fixed a stale module list.
- Replaced the few stray real em dashes in the codebase with its own
  established `--` convention (one outlier line, one document written
  in a different voice than the rest of the repo).

## 2026-08-21

- Fixed a real `NameError`-shaped bug ("'request' is undefined")
  breaking pagination past page 1 on any list screen.
- The 500 error page is now branded, and 403/404 pages stopped losing
  their branding depending on the request's `Accept` header.
- Ticket list: widened the title column, shrunk the description text to
  make room.
- Assets: fixed the nav sidebar's count silently excluding CSV/JSON-
  imported assets; fixed CI counts getting stuck until a manual edit;
  added sort, search, and autocomplete to the assets list.
- Event Promotion Policies: added editing (previously create/delete
  only), and combine-by-title auto-merge for near-duplicate policies.
- Tickets list: fixed the bulk action-menu layout, defaulted the view to
  active tickets, added mass-resolve and an asset filter -- then fixed
  "Mass resolve" actually applying the wrong status (corrected to "Mass
  close"), and right-aligned the bulk-select bar.
- Mass close now records who reviewed each ticket as an acknowledgment
  comment, instead of closing silently.
- Client portal: added the same All active/All statuses filter to
  Report Something that the authenticated ticket list already had.
- Activity feed: system-generated entries are labeled "RAIN System"
  instead of the confusing "Someone".

## 2026-08-20

- Client portal: burger nav for mobile screens, plus fixes found while
  testing it live on an actual phone.
- Fixed change-approval syslog emission and corrected document-diff
  change-detection gating.
- Made `pgvector` optional (bootstrap now asks, for a Postgres that
  can't create the extension or doesn't ship it -- e.g. standard RDS in
  AWS GovCloud) and made Caddy optional (`WEB_FRONTEND=false`).
- Fixed the single-container deployment story end to end after live
  testing surfaced real gaps.
- Redesigned the CSS token system away from the generic default look;
  swapped the initial warm neutral palette for a cooler stone/slate one.
- SAML: added debug logging, a graceful failure mode, and a 403
  diagnosis path; made JIT provisioning create-only (never re-syncs an
  existing user's attributes on a later login).
- Syslog listener: fixed the single-container status check and improved
  visibility into silently-dropped events.
- Outbound email/Slack/webhook sends are now logged; added an SMTP
  test-send button to Admin.
- Live event feed: view an event's full raw message.
- Full event detail is now preserved when promoting an event to a
  ticket (previously some of it was lost in translation).
- Long ticket descriptions are clamped to 15 lines with a "Show more"
  toggle instead of stretching the page.

## 2026-08-19

- **Service Catalog**: tenant-defined request forms (e.g. "new laptop",
  "VPN access") that produce tickets, the first consumer of the
  Approval Flow machinery beyond Change tickets -- plus follow-up UI
  fixes (form alignment/grouping, approval scoped to Change tickets
  specifically, the portal restructured around anonymous Request/Report
  access) and an Approval Flows step-row alignment fix shared with it.
- README cleanup; a bigger logo; a mobile-friendly client portal pass;
  a ticket timeline modal for a lighter-weight "just the updates" view.
- Self-service password reset via SMTP.

## 2026-08-18

- Syslog listener: auto-detects and parses CEF, JSON, and Splunk-style
  key=value message bodies alongside plain syslog text, no per-source
  configuration needed.
- Bootstrap scripts (`bootstrap.py`/`.sh`/`.ps1`) now ask interactive
  deployment questions on first run instead of just generating secrets.

## 2026-08-17

- Documented the full placeholder catalog (every `{{...}}` template
  token available to notification/webhook templates) via in-app help
  popovers and the user guide.
- Added `docs/itsm-controls-mapping.md`, a FedRAMP/NIST 800-53 controls
  reference mapping specific controls to RAIN's own record-keeping
  (removed and re-added once over a GitHub rendering issue on the raw
  file; later expanded with Moderate/Low baseline estimates and indirect
  coverage).
- README: added a Motivation section covering the "bring your own"
  monitoring/SIEM/XDR/AV framing and why syslog is the event bus, an
  embedded screenshot, and a note that RAIN ships with no pre-defined
  asset types on purpose.
- Login page also shows the database schema build number now, matching
  the authenticated app's user menu.

## 2026-08-16

- Ticket watchers by email; mark-problematic and add-watcher as Platform
  Response Rule actions; a one-click ticket Escalate button; the portal
  gained a "today's events" listing pulled from the tenant calendar.
- A full docs pass: README, architecture, user guide, and a grouped/
  described Swagger API spec.
- Login: replaced a silent client-side-only email check with a real
  server-side validation.
- **S3 document storage** and the single-container **"minimal mode"**
  deployment shape (`EMBED_WORKER=true` + external Postgres + no Caddy).
- A **Helm chart** (`charts/rain/`) added, mirroring the same deployment
  shapes as `docker-compose.yml`/`docker-compose.minimal.yml`.

## 2026-08-15

- Assets: pretty `CI-000123`-style URLs, editable asset types.
- Security: bumped several pinned dependencies flagged by a container
  vulnerability scan, and specifically fixed CVE-2026-69247
  (`cryptography`) and CVE-2026-8643 (`pip`).
- Fixed the Dockerfile not actually cache-busting pip's own upgrade on
  every build.
- Syslog listener: source-routing rules became editable, not just
  create/delete.
- **Public incident portal** launched: file an incident with or without
  an account, immediately followed by a dedicated security/critique
  review pass on it.
- The "chronic" ticket flag was renamed "problematic"; added ticket
  watchers and approval-pending emails; widened the portal for
  authenticated visitors; added an XML/JSON document editor.
- Gated FastAPI's `/docs`, `/redoc`, and `/openapi.json` behind
  `require_internal_admin` (previously reachable by anyone).
- **Correlation Rules**: added River-backed ML anomaly detection
  (`HalfSpaceTrees`) alongside the existing threshold-based repetition
  rule, plus a verbiage cleanup, a portal layout rework, and jumping
  straight to a record from a typed `CI-`/`INC-`/`DOC-` number in search.

## 2026-08-14

- **Centrally-configured Webhooks** (Admin > Webhooks): one URL/headers/
  payload/timeout definition reused everywhere a webhook call is needed
  -- Platform Response Rules and Document's "populate from webhook" (with
  change-diff alerting) were the first two consumers.
- User menu: shows the current database schema build number.
- Layout: assets list and the main content area now use the full page
  width; dropped an unused "Cloud Sync" stub feature.
- Calendar polish, and document auto-refresh from its configured
  webhook.
- Deployment: support for an external/managed Postgres (`POSTGRES_URL`),
  a custom app port, and skipping Caddy entirely.
- Editing an already-approved Change ticket now nullifies its collected
  approvals instead of leaving stale sign-off on a since-changed record.
- **SAML 2.0 SSO** implemented, replacing an earlier OIDC placeholder.
- **Keyword search** across Tickets and Documents (Postgres full-text,
  `tsvector`/GIN) -- `pgvector` reserved for a future semantic-search
  pass, not populated yet.
- Added the `client_admin` role (tenant-scoped admin rights); split
  Admin into Platform Administration and Tenant Administration; gave
  tickets and documents pretty URLs (`/tickets/INC-000001`) instead of
  raw numeric IDs; fixed a real tab-switching bug found along the way.
- Calendar: daily/weekly/monthly recurrence; moved Asset Types into
  Tenant Administration.
- Syslog listener: configurable event retention; Notification channels
  (email/Slack/webhook) with editable, macro-driven message templates.
- Document links: a pill selector for link type instead of a raw
  dropdown, referencing tickets by number instead of internal ID.
- Added `docs/user-guide.md` (a task-oriented user manual), expanded
  same-day into a full screen-by-screen reference.

## 2026-08-13

- Threshold-based correlation rules for Event Promotion Policies (fire
  after N matching events in a trailing window, not just one); reworked
  the Linked Documents panel layout.
- Hover help icons added across the UI; fixed static-asset cache-busting
  not actually busting the cache.
- UI polish: normalized sign-out button styling, shrunk the Linked
  Documents panel width.
- Fixed a disappearing menu button; added a breadcrumb; fixed PDF logo
  distortion (non-square logos were squashed into a fixed box).
- Replaced "New X" tabs sitewide with a button + modal pattern, and
  dropped a redundant page `<h1>` next to it.
- Collapsed the topbar user block into an icon menu; added a "Session
  for X" tenant badge (later trimmed to just the tenant name).
- Ticket assignment and affected-asset editing, plus general button
  consistency and a document-link rework.
- **Groups** and **Approval Flows** added -- the foundation Change
  ticket approvals (below) are built on.
- **Change ticket type**: promotion from an existing incident/
  vulnerability, a required approval workflow, and a calendar-visible
  scheduled window; fixed a live modal-close regression found along the
  way.
- **LDAP auth provider**: bind-DN configuration, periodic user/group
  sync, no local password for a synced user.
- Fixed a collapsed-sidebar flyout hover gap and dead content width;
  polished table headers.
- Tickets list redesign: a real filter toolbar, color-coded type pills,
  full width, sortable columns; Platform Response Rule action fields
  became conditional on the selected action type.
- Added the "chronic" flag (renamed "problematic" two days later), a
  per-row quick-action menu, and merged the filter toolbar further.
- More tickets-list/row-menu polish; a chronic-flag toggle on the detail
  page.
- Moved rule configuration out of the Tickets area into Admin; added
  missing edit UIs; a bulk triage menu for the live event feed.
- Ticket detail: editable title, consistent metadata row heights.
- **Ticket detail overhaul**: editable severity, a unified chronological
  activity log, approval enforcement, sidebar nav counts, asset<->ticket
  linking, and reusable export column profiles -- plus assorted fixes.

## 2026-08-12

Initial release. The first day's commits laid down the whole platform
foundation in three large milestones, then spent the rest of the day on
early polish and real-world deployment fixes:

- **Milestone 1 -- Platform foundation + Asset Registry**: multi-tenant
  schema-per-tenant Postgres, the in-app setup wizard, the Admin
  console, session-based auth with `internal_admin`/`client` roles, and
  the Asset Registry (custom asset types with per-type custom fields,
  CSV/JSON import/export).
- **Milestone 2 -- Ticketing**: the built-in syslog listener, Event
  Promotion Policies (regex-matched auto-promotion into tickets), and
  Platform Response Rules (Slack/email notifications on new tickets).
- **Milestone 3 -- Document repository**: `DOC-xxxxxx` records with file
  attachments, linkable to any ticket or asset.
- A round of real-Docker-run fixes found by actually deploying the
  thing: dropped a nonexistent compiler package from the `db` image,
  switched to pgvector's official image instead of compiling it,
  corrected `alembic`'s script-location resolution, fixed migrations
  missing from the image entirely and not persisting, serialized
  concurrent migration runs, fixed `bootstrap.ps1` on Windows PowerShell
  5.1, and added a debug-response mode -- all written up in
  `docs/architecture.md`'s own "lessons from the first real Docker run"
  section.
- A navigation redesign, tabbed CRUD screens, and PDF export.
- A resizable sidebar, custom font choice, Platform Events (renamed
  Platform Response Rules later that day), pagination, and Excel export.
- Tenant-customizable ticket statuses, a combined status/comment
  activity feed, and moving instance configuration into Admin.
- A per-tenant Calendar: recurring entries, a syslog bridge (synthesize
  a syslog event on each occurrence), and `.ics` import/export.
- Sidebar nav search (typeahead over the rendered tree).
- Renamed "Platform Events" to "Platform Response Rules" and "Tickets"
  to "Records Authority" (the ticketing area kept the "Tickets" name in
  the UI going forward, per every later entry in this log).
- An inline text/Markdown document editor, PDF body embedding for
  documents, and a document-preview modal.
