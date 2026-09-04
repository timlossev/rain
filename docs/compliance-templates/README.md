# Compliance register starter templates

Pre-built tenant configuration bundles (the same JSON shape Admin >
Config Bundles exports/imports) that seed a custom asset type and its
fields for a common compliance register, so it doesn't have to be built
by hand from scratch:

- `risk-register.json` -- a Risk asset type with category, likelihood,
  impact, treatment, treatment plan, and next review date fields.
- `subprocessor-register.json` -- a Subprocessor asset type with service
  provided, data processed, hosting region, contract/DPA review date,
  and certification-on-file fields.
- `piv-cac-card-issuance.json` -- a PIV/CAC Card asset type (serial
  number/FASC-N, card type, issuing agency, sponsor, background
  investigation tier, issue/expiration dates, and status) for tracking
  federal PIV/CAC credential issuance -- each Asset's own "Name" is the
  cardholder.
- `software-license-register.json` -- a Software License asset type
  (vendor, license type, seat count, annual cost, renewal date,
  auto-renew flag, internal owner, vendor portal URL, and status) for
  vendor/software-asset-management tracking -- each Asset's own "Name"
  is the product or agreement.
- `cloud-environment-register.json` -- a Cloud Environment asset type
  (provider, account/subscription/project ID, environment, region, IaC
  repo URL, owner, last discovery run, drift status) for tracking a
  cloud account alongside a linked infrastructure-drift-monitoring
  document -- see "Infrastructure drift detection" in
  `docs/user-guide.md`. Each Asset's own "Name" is the environment's
  short name (e.g. "prod-aws-us-east-1").
- `encryption-key-cert-register.json` -- an Encryption Key /
  Certificate asset type (kind, algorithm, issuer/provider, storage
  location, issued/expiration dates, rotation owner, auto-rotates, and
  status). Tracks the credential's lifecycle only -- never store actual
  key material or private keys here. Each Asset's own "Name" is the
  key/certificate name or CN.
- `system-interconnection-register.json` -- a System Interconnection
  asset type (system A/B, connection type, data exchanged,
  authorization/review dates, and status). Link the actual
  Interconnection Security Agreement, if there is one, as a Document on
  the asset's own Links tab rather than pasting it into a field. Each
  Asset's own "Name" is a short label for the connection.
- `contractor-access-register.json` -- a Contractor Access asset type
  (vendor/employer, role, internal sponsor, access level, background
  check status, engagement dates, and access status) for tracking
  third-party *individuals* with access, distinct from the Subprocessor
  Register's vendor-company level. Each Asset's own "Name" is the
  contractor's name.
- `data-inventory-register.json` -- a Data Asset type (data category,
  classification level, system/location, owner, retention period, and
  applicable regulation) for a basic data inventory/classification
  register. Each Asset's own "Name" is the data asset's name.
- `poam-tracking-fields.json` -- ticket-scoped, not an asset type. A
  POA&M item's lifecycle (opened, tracked, closed or risk-accepted) is
  a ticket's lifecycle, not a persistent asset's: POA&M ID, finding
  source, CVE/finding ID, original risk rating, scheduled completion
  date, point of contact, affected systems, deviation type and
  justification. File a POA&M item as a vulnerability ticket (or
  whichever type the underlying finding actually is) and these fields
  show up on it. One real gap: FedRAMP's own POA&M template expects
  discrete, individually-dated milestones per item, and RAIN has no
  first-class milestone list -- a ticket's timestamped comment thread
  and status history is the practical substitute, not a literal
  replacement.
- `nessus-finding-fields.json` -- also ticket-scoped, and deliberately
  complementary to poam-tracking-fields.json rather than overlapping it:
  this one holds the raw scan data (plugin ID, plugin name/family,
  scanned host, port, protocol, CVSS base score, the scanner's own risk
  factor, last-seen-in-scan date), not the remediation-lifecycle
  metadata. Entirely optional -- Tickets > Import's "Nessus scan export
  (.nessus)" format works with zero custom fields installed at all
  (every finding still lands as a real, deduped vulnerability ticket
  with the full human-readable detail in its description); installing
  this template just gets you that same data as separate, filterable/
  exportable columns instead of only free text. Upload the plain-XML
  `.nessus` file directly (not the separate, proprietary Nessus DB
  format -- see rain.modules.tickets.nessus_parser's own docstring) and
  the mapping screen arrives pre-filled: the parser's own column names
  are chosen to exactly match this importer's target labels and, when
  installed, this template's own field labels, so there's nothing left
  to map by hand, just to review. A CSV export works too, the same way
  it always has, if you'd rather map columns by hand or your source
  isn't Nessus. The import screen's own "Dedup key" field is what makes
  a monthly re-scan safe to just re-import: a still-open match is left
  alone (its fields still refresh, so "last seen" stays current), a
  closed match is reopened and flagged recurring instead of creating a
  duplicate. Verified live end to end: a sample finding imported once
  (created), imported again unchanged (left alone), closed by hand, then
  imported a third time (reopened, flagged problematic, commented) --
  never more than the one ticket for that key throughout.
- `fedramp-ocr-fields.json` -- ticket-scoped, and additive alongside
  poam-tracking-fields.json rather than a replacement for it. Under
  FedRAMP's 2026 Consolidated Rules (CR26), the monthly CSP-maintained
  POA&M is being superseded by a quarterly Ongoing Certification Report
  (OCR) plus a synchronous Quarterly Review -- POA&Ms don't disappear,
  they become primarily an *agency*-owned artifact ("the POA&M belongs
  to the agency when the action belongs to the agency," per fedramp.gov)
  while CSPs report a rolling summary instead. This template covers the
  three OCR content areas that are genuinely per-ticket concepts:
  `accepted_vulnerability`/`acceptance_justification`/`accepted_by`/
  `acceptance_date`/`next_ocr_period` for the OCR's "accepted
  vulnerabilities" section, `fedramp_reportable_incident` (usable on
  incident tickets) for its incident section, and `transformative_change`
  (usable on change tickets) for its transformative-changes section. The
  OCR's other required content (certification-data changes, which
  agencies use the service, updated security recommendations) is
  organizational narrative, not per-finding data -- authoring the actual
  quarterly report as a RAIN Document, with a quarterly `CalendarEntry`
  reminder, is the natural fit for that half, not a custom field.
  poam-tracking-fields.json stays exactly as it was for non-FedRAMP
  programs and for authorizations still on the pre-CR26 model during the
  transition (mandatory CR26 adoption is January 1, 2027) -- nothing
  here replaces it.

To use one: Admin > Config Bundles > Tenant > Import, and pick the file.
Each only carries `custom_fields` (and, for every asset-type template,
`asset_types`) -- importing one adds that to the active tenant without
touching anything else already configured there (tickets, webhooks,
groups, users, and so on are untouched, since the bundle simply doesn't
mention them). Once imported, an asset-type template populates like any
other asset type under Assets > + New, using its own custom-fields form
the same way you would for any other asset; the three ticket-scoped
templates' fields show up directly on the ticket form and in the CSV
importer's own column-mapping screen, the same as any other
ticket-scoped custom field.

Every one of these files carries a `source_tenant_slug`/
`source_tenant_name` of `"template"`/"... starter template" -- that's
just export provenance metadata (where `apply_tenant_bundle` originally
wrote it from), never read back on import. A tenant bundle always
imports into whichever tenant your session currently has active (Admin
> Tenants > Switch to); it can't create a new tenant or target a
different one, and nothing about the file's own contents changes that.

These are starting points, not a fixed schema -- rename, add, or drop
fields afterward under Admin > Asset Types (or, for the three
ticket-scoped templates, Tickets > Custom Fields) the same as you
would for any asset type or field you built yourself.
