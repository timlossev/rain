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
  metadata. Tenable's own CSV export from a Nessus scan uses column
  names close enough to these labels (Plugin ID, CVSS Base Score, Risk,
  Host, Protocol, Port, ...) that the existing CSV ticket importer
  (Tickets > Import) can map a real scan's findings onto these fields
  today, with no new code -- add a "Type" column set to `vulnerability`
  on every row first, since the importer has no fixed-value option and
  needs a real column to map `ticket_type` from. Verified live: a
  2-finding sample scan CSV, mapped through the existing import
  screen, created two vulnerability tickets with plugin ID/host/port
  landing on the right fields. What this *doesn't* give you: the CSV
  importer has no dedup key, so re-importing next month's scan of the
  same hosts creates fresh duplicate tickets for every still-open
  finding rather than recognizing them -- a real re-scan workflow needs
  a dedicated `.nessus` (XML) importer with its own dedup/regression
  logic on top of this same field set, not yet built.

To use one: Admin > Config Bundles > Tenant > Import, and pick the file.
Each only carries `custom_fields` (and, for every asset-type template,
`asset_types`) -- importing one adds that to the active tenant without
touching anything else already configured there (tickets, webhooks,
groups, users, and so on are untouched, since the bundle simply doesn't
mention them). Once imported, an asset-type template populates like any
other asset type under Assets > + New, using its own custom-fields form
the same way you would for any other asset; the two ticket-scoped
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
fields afterward under Admin > Asset Types (or, for the two
ticket-scoped templates, Tickets > Custom Fields) the same as you
would for any asset type or field you built yourself.
