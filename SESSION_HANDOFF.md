# RAIN session handoff — resume here

Saved at user's request right before a machine reboot (disk was reported 0 bytes
free on C:, which was breaking Docker — see "Blocking issue" below). Nothing was
mid-write / no file was left half-edited; all edits described as "done" below were
actually saved to disk before this note was written.

## Blocking issue (check first on resume)
- C: drive was reported as **0 bytes free**, which was causing Docker Desktop's
  daemon to throw intermittent 500s / EOF errors and made `docker system prune`
  itself fail (daemon couldn't write enough to even prune). User said "I'll clean
  the space" and then asked to reboot instead.
- **On resume: confirm free disk space first** (`Get-PSDrive C`), then confirm
  `docker ps` / `docker compose ps` work, before attempting any build/deploy.
- Unrelated large-looking untracked files one level up from `RAIN/` that were
  NOT touched or investigated (flagged only, never deleted):
  `../sources_2026-05-21_15-55-51.csv`, `../wallpaper.png`, `../curated_systems.png`,
  `../validate_log.txt`, `../validate_run.log`, `../Legal framework/`, `../__pycache__/`.

## Work completed this session (all saved to disk, NOT yet rebuilt/deployed/verified/committed)

### 1. Help-icon ("?") sweep — DONE, all ~34 templates
Every content page with an `<h1>` now imports `_help.html` and wraps its heading
with `{{ help.help_icon("...") }}`, with the old inline explanatory `<p class="muted">`
text (where present) folded into the popover text. Confirmed via `grep` that every
`.html` template containing `<h1>` except the three error pages
(`errors/403.html`, `errors/404.html`, `errors/no_tenant.html` — intentionally
excluded) now imports `_help.html`.

Last-edited-in-this-pass files (earlier ones were done in the prior session
before compaction — see full list in prior summary if needed):
`tickets/platform_event_detail.html`, `tickets/export.html`, `tickets/list.html`,
`assets/fields.html`, `assets/types.html`, `admin/tenants.html`, `admin/users.html`,
`documents/list.html`, `assets/list.html`, `admin/user_edit.html`, `assets/export.html`,
`assets/form.html`, `tickets/live.html`, `documents/form.html`, `tickets/form.html`,
`assets/import_result.html`, `assets/import_preview.html`, `assets/import.html`,
`admin/dashboard.html`.

### 2. Real bug found + fixed: help-icon text showing unconditionally (not just on hover)
Root cause was **stale cached CSS** in the browser (same class of bug as the earlier
stuck-modal issue), not a real CSS/logic defect — verified via `curl` that the
*live-served* `app.css` already had the correct hover-only rule
(`.help-icon-popover { display: none; }` + `.help-icon-wrap:hover .help-icon-popover,
.help-icon-wrap:focus-within .help-icon-popover { display: block; }`). User confirmed
after a hard refresh it displayed correctly.

**Structural fix applied** (to stop this recurring on every future deploy, since this
is the second time a stale-cache issue has looked like a live bug):
- `backend/src/rain/web/templating.py`: added `ASSET_VERSION = str(int(time.time()))`
  computed once at process start, exposed as Jinja global `asset_version`.
- `backend/src/rain/web/templates/base.html`: `app.css` and `app.js` `<link>`/`<script>`
  tags now have `?v={{ asset_version }}`.
- `backend/src/rain/web/templates/tickets/live.html`: `live.js` script tag likewise
  has `?v={{ asset_version }}`.
- This has been **built once successfully** (`docker compose build app` succeeded)
  but the follow-up `docker compose up -d app` failed partway through due to the
  disk-full/Docker-daemon issue above — **so the fix is NOT yet live/deployed**,
  and NOT yet re-verified against the running stack after this specific change.

### 3. New requests queued, NOT yet started (design/investigation only, no edits made)
Arrived rapid-fire near the end of the session, in this order:

  a. **"Why are the View, Download, Export to PDF, Logout, and Unlink buttons on
     the ticket view page of a different size and style? Can you make sure that
     all buttons across the system have identical styling?"**
     - Root cause identified (not yet fixed): View/Download/Export-to-PDF/Unlink
       all already use `class="btn btn-sm"` (+ `btn-danger` for Unlink) consistently.
       The outlier is **Sign out**, in `base.html` line ~83:
       `<button class="btn-link sign-out-btn" type="submit" title="Sign out">` —
       `.btn-link` is `all: unset` and `.sign-out-btn` (app.css ~line 216) is a
       fully custom hand-rolled style (flex row, icon+text, own font-size, no
       border/background), entirely disjoint from `.btn`/`.btn-sm`. Plan: change
       markup to `class="btn btn-sm sign-out-btn"` (keep `sign-out-btn` only for
       icon-gap tweaks if still needed) so it visually matches every other button
       in the app. Also sweep for any other `.btn-link`-based buttons that should
       actually be `.btn`.

  b. **"Also make the documents panel 50% of the incident metadata panel — it
     doesn't have enough info to justify such a waste of space."**
     - This is on `backend/src/rain/web/templates/tickets/detail.html`, the
       `.ticket-top-row` flex row (currently: metadata card `flex:1; min-width:280px;`,
       Linked Documents wrapper `flex:2; min-width:340px;` — this ratio was set
       **wider** for docs earlier this session at the user's prior explicit request;
       this new request reverses that). Plan: flip so Linked Documents column is
       ~50% width of the metadata column, e.g. metadata `flex:2`, docs `flex:1`
       (or explicit percentage/max-width), keeping `min-width` reasonable so it
       still wraps sanely on small screens (the flexbox-row rewrite from earlier
       in the session, `.doc-link-row`, should tolerate the narrower width fine
       since it already wraps rather than using a fixed-width table).

  c. **"Everywhere where we have a 'New something' tab (Event Policies -> New
     policy) replace the tab with a button + modal window. Tabs are for
     displaying, forms should go into a modal window."**
     - Large sitewide pattern change. Every list+create page currently uses the
       `data-tabs` / `tab-btn` / `tab-panel` pattern with an "Active X" tab and a
       "New X" tab containing the create form. Known pages using this pattern
       (non-exhaustive — grep `data-tab-btn="new"` across `templates/` to enumerate
       precisely on resume):
       `tickets/rules.html` (Platform Response Rules / Event Policies),
       `tickets/correlation_rules.html`, `assets/types.html`, `assets/fields.html`,
       `admin/tenants.html`, `admin/users.html`, `admin/ticket_statuses.html`,
       `admin/notification_channels.html`, `admin/auth_providers.html`, and
       possibly others (`calendar` new-entry is already a separate page, not a
       tab, so likely out of scope — verify). Plan: introduce a reusable modal
       pattern (probably a new `_modal.html` partial/macro, or extend the existing
       `.modal-overlay`/`.modal-box` CSS already used for the document-preview
       modal) — a "+ New X" button that toggles a modal containing the existing
       create `<form>` markup verbatim, and remove the tab-based "New" panel/tab
       button. The "Active X" list stays as a plain page (no tabs needed once
       there's only one panel) or could keep tabs if there end up being other
       non-create tabs — needs a quick design pass, not just mechanical find/replace.
     - **Not started at all** — no files touched for this item.

  d. **"All subheaders such as 'Event policies' should probably go to the unused
     white space where we have the user name and the user profile. Also hide the
     user profile button to maybe a button depicting a user icon and only show
     that info in a user menu, including the Sign out button on the top right."**
     - Topbar/layout redesign. Currently `header.topbar` (base.html ~line 76-89)
       has: a left-aligned "Menu" toggle button, and a right-aligned
       `.topbar-user` block showing display name + role badge + inline Sign-out
       button. Page-specific `<h1>` (e.g. "Event Policies", "Correlation Rules")
       currently renders inside `.content`, not in the topbar.
     - Plan (needs a design decision before implementing, flag to user on
       resume rather than guessing): move the page's `<h1>`-equivalent text into
       the topbar's middle/left empty space (would need a new Jinja block, e.g.
       `{% block page_heading %}` or reuse `{% block title %}`'s text, rendered
       into the topbar via a template inheritance hook — every one of the ~34
       templates touched in item 1 would need at least a look, though likely only
       a change to `base.html` + maybe passing a `page_title` variable is enough
       if we derive it rather than hand-editing every template). Collapse the
       user info + Sign out into a single icon button (e.g. a person/user glyph)
       that reveals a dropdown/menu on click or hover containing: display name,
       role badge, active tenant (if any), and the Sign out button — likely a
       small `.user-menu` component analogous to `.help-icon-wrap` (CSS-only
       hover/focus-within reveal, consistent with this project's no-JS-framework
       CSS-interaction pattern) or click-toggled via a small vanilla-JS handler
       in `app.js` if hover isn't appropriate for a menu with clickable items
       (hover-only menus are usually worse UX for actionable items — lean toward
       click-toggle + click-outside-to-close, need a tiny JS addition).
     - **Not started at all** — no files touched for this item.

## Suggested resumption order
1. Confirm disk space is actually free and Docker is healthy again.
2. `docker compose up -d app` to deploy the already-built help-icon +
   cache-busting fix (rebuild first if the image was pruned/lost during cleanup —
   check `docker images` for `rain-app`).
3. Re-run the verification sweep (mint a session via `tenant_session`/direct DB
   insert as established, curl representative pages, confirm `help-icon-wrap`
   markup present and pages 200 OK) — the previous verification attempt hit a
   303-redirect-to-`/admin/tenants` snag because the minted internal_admin test
   session had `active_tenant_id = user.tenant_id` (null for internal_admin);
   fix by setting `active_tenant_id` to a real tenant id (e.g. first row in
   `control.tenants`) when minting the next verification session.
4. Commit + push the help-icon sweep and cache-busting fix (item 1 + 2 above).
5. Then work through queued items 3a → 3b → 3c → 3d in that order (roughly
   easy/contained → large/sitewide → needs-a-design-decision), asking the user
   a clarifying question before starting 3d specifically (hover vs click-toggle
   menu; whether page subheading replaces or supplements the topbar).
6. After that, return to the still-earlier-paused backlog (also still pending,
   untouched this session): correct the RAIN acronym in docs, refresh
   `docs/architecture.md` + `README.md` with latest developments (Correlation
   Rules, Calendar, renames, etc.), build tenant-specific Groups, stage "Change"
   as a third ticket type.

## Standing conventions (still in force)
- Windows/PowerShell + Docker PATH workaround per call:
  `$env:PATH += ";C:\Program Files\Docker\Docker\resources\bin"`.
- Never declare something done without verifying against the real running stack
  (curl / in-container script via `tenant_session(...)`), then clean up any test
  session/data created for verification.
- Prefer targeted `docker compose build/up <service>` over full teardown — user
  wants the stack left running.
- Commit with detailed messages; push to `origin` (https://github.com/timlossev/rain)
  after each commit.
- Use DEBUG-mode tracebacks when debugging.

This file (`RAIN/SESSION_HANDOFF.md`) is scratch/handoff-only — not part of the
product. Safe to delete once its contents have been re-absorbed into the next
session's context (e.g. after resuming and confirming everything above is
accounted for).
