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

To use one: Admin > Config Bundles > Tenant > Import, and pick the file.
Each only carries `asset_types` and `custom_fields` -- importing one adds
that asset type and its fields to the active tenant without touching
anything else already configured there (tickets, webhooks, groups,
users, and so on are untouched, since the bundle simply doesn't mention
them). Once imported, populate it like any other asset type under
Assets > + New, and use its own custom-fields form the same way you
would for any other asset.

These are starting points, not a fixed schema -- rename, add, or drop
fields afterward under Admin > Asset Types the same as you would for any
asset type you built yourself.
