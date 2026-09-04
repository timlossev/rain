# Compliance register starter templates

Pre-built RAIN config bundles -- the exact format Admin > Config Bundles
exports and imports, just renamed `.rain` instead of `.json` to make
clear these aren't meant to be hand-edited as generic data: import one
through that same screen and it seeds a custom asset type or a set of
ticket fields for a common compliance register, with no code involved.

| File | Seeds | Why |
|---|---|---|
| `risk-register.rain` | Risk asset type | RA-3 (Risk Assessment) |
| `subprocessor-register.rain` | Subprocessor asset type | SR-2/SR-6, PCI-DSS Req 12.8, ISO 27001 5.19-5.23 |
| `piv-cac-card-issuance.rain` | PIV/CAC Card asset type | IA-2/PE-2, PS-3 (federal credential issuance) |
| `software-license-register.rain` | Software License asset type | CM-10 (Software Usage Restrictions) |
| `cloud-environment-register.rain` | Cloud Environment asset type | CM-2/CM-8(3)/SI-7 (pairs with the drift-detection pattern in `docs/user-guide.md`) |
| `encryption-key-cert-register.rain` | Encryption Key/Certificate asset type | SC-12/SC-13, ISO 27001 8.24 |
| `system-interconnection-register.rain` | System Interconnection asset type | CA-3 |
| `contractor-access-register.rain` | Contractor Access asset type | PS-7 (individual level, distinct from the Subprocessor Register's company level) |
| `data-inventory-register.rain` | Data Asset type | RA-2, ISO 27001 5.12/5.13 |
| `poam-tracking-fields.rain` | *Ticket* fields | CA-5 (POA&M) |
| `nessus-finding-fields.rain` | *Ticket* fields | RA-5/RA-7 -- optional; Tickets > Import reads a `.nessus` file natively either way |
| `fedramp-ocr-fields.rain` | *Ticket* fields | FedRAMP CR26's Ongoing Certification Report -- additive alongside the POA&M template, not a replacement for it (see `docs/itsm-controls-mapping.md`'s CA-5 entry) |

Everything except the three ticket-scoped ones (POA&M, Nessus, FedRAMP
OCR) seeds an asset type plus its fields; those three seed tenant-wide
ticket custom fields instead, since that data tracks a ticket's own
lifecycle, not a persistent asset's.

## Why these

Each one closes a specific gap `docs/itsm-controls-mapping.md` and
`docs/eucs-compliance-assessment.md` identify against real frameworks
(FedRAMP/NIST 800-53, PCI-DSS, ISO 27001, EUCS) -- picked because
they're common enough that most compliance-minded tenants would
otherwise build the same custom asset type or field set by hand. None
of them are required for RAIN to work; they're a five-minute head
start, not a dependency.

**Don't see your framework?** These aren't the only ones that'll ever
exist -- if you're working against a program we haven't covered (a
different national framework, an industry-specific one, whatever), say
so and we'll put one together.

## Using one

Admin > Config Bundles > Tenant > Import, pick the file. Each only
carries `custom_fields` (and, for the asset-scoped ones, `asset_types`)
-- nothing else already configured (tickets, webhooks, groups, users)
is touched. Rename, add, or drop fields afterward the same as anything
you'd built yourself: Admin > Asset Types, or Tickets > Custom Fields
for the three ticket-scoped templates.

A template's `source_tenant_slug`/`source_tenant_name` are just export
provenance -- never read on import. A bundle always imports into
whichever tenant your session currently has active; it can't create a
new tenant or target a different one.
