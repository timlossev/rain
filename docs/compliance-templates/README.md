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
- `poam-tracking-fields.json` -- the one template that isn't an asset
  type. A POA&M item's lifecycle (opened, tracked, closed or
  risk-accepted) is a ticket's lifecycle, not a persistent asset's, so
  this seeds *ticket* custom fields instead (POA&M ID, finding source,
  CVE/finding ID, original risk rating, scheduled completion date,
  point of contact, affected systems, deviation type and
  justification) -- applying tenant-wide, across all three ticket
  types, the same as every ticket-scoped field does. File a POA&M item
  as a vulnerability ticket (or whichever type the underlying finding
  actually is) and these fields show up on it. One real gap: FedRAMP's
  own POA&M template expects discrete, individually-dated milestones
  per item, and RAIN has no first-class milestone list -- a ticket's
  timestamped comment thread and status history is the practical
  substitute, not a literal replacement.

To use one: Admin > Config Bundles > Tenant > Import, and pick the file.
Each only carries `custom_fields` (and, for every one but poam-
tracking-fields.json, `asset_types`) -- importing one adds that to the
active tenant without touching anything else already configured there
(tickets, webhooks, groups, users, and so on are untouched, since the
bundle simply doesn't mention them). Once imported, an asset-type
template populates like any other asset type under Assets > + New,
using its own custom-fields form the same way you would for any other
asset; poam-tracking-fields.json's fields show up directly on the
ticket form, the same as any other ticket-scoped custom field.

Every one of these files carries a `source_tenant_slug`/
`source_tenant_name` of `"template"`/"... starter template" -- that's
just export provenance metadata (where `apply_tenant_bundle` originally
wrote it from), never read back on import. A tenant bundle always
imports into whichever tenant your session currently has active (Admin
> Tenants > Switch to); it can't create a new tenant or target a
different one, and nothing about the file's own contents changes that.

These are starting points, not a fixed schema -- rename, add, or drop
fields afterward under Admin > Asset Types (or, for poam-tracking-
fields.json, Tickets > Custom Fields) the same as you would for any
asset type or field you built yourself.
