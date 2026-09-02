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

To use one: Admin > Config Bundles > Tenant > Import, and pick the file.
Both only carry `asset_types` and `custom_fields` -- importing one adds
that asset type and its fields to the active tenant without touching
anything else already configured there (tickets, webhooks, groups,
users, and so on are untouched, since the bundle simply doesn't mention
them). Once imported, populate it like any other asset type under
Assets > + New, and use its own custom-fields form the same way you
would for any other asset.

These are starting points, not a fixed schema -- rename, add, or drop
fields afterward under Admin > Asset Types the same as you would for any
asset type you built yourself.
