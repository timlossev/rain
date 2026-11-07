# Compliance register starter templates

Pre-built RAIN config bundles -- the exact format Admin > Config Bundles
exports and imports, just renamed `.rain` instead of `.json` to make
clear these aren't meant to be hand-edited as generic data: import one
through that same screen and it seeds a custom asset type or a set of
ticket fields for a common compliance register, with no code involved.

Three subfolders, by what you do with the file:

| Folder | Contents | Where it's used |
|---|---|---|
| `bundles/` | `.rain` config bundles | Admin > Config Bundles > Tenant > Import |
| `transforms/` | `.jq` export transforms | Tickets/Assets > Export's "JSON transform (optional)" |
| `data/` | Real register *data* (`.csv`), not config, plus the script that generates it -- see [`data/README.md`](data/README.md) for exactly what's ready to import as-is vs. what needs a script run first | Assets > Import |

| File | Seeds | Why |
|---|---|---|
| `bundles/risk-register.rain` | Risk asset type | RA-3 (Risk Assessment) |
| `bundles/subprocessor-register.rain` | Subprocessor asset type | SR-2/SR-6, PCI-DSS Req 12.8, ISO 27001 5.19-5.23 |
| `bundles/piv-cac-card-issuance.rain` | PIV/CAC Card asset type | IA-2/PE-2, PS-3 (federal credential issuance) |
| `bundles/software-license-register.rain` | Software License asset type | CM-10 (Software Usage Restrictions) -- vendor agreements and renewals, not what's actually running (see `software-inventory-register.rain` below for that) |
| `bundles/cloud-environment-register.rain` | Cloud Environment asset type | CM-2/CM-8(3)/SI-7 (pairs with the pattern in [`docs/drift-detection-showcase.md`](../drift-detection-showcase.md)) |
| `bundles/encryption-key-cert-register.rain` | Encryption Key/Certificate asset type | SC-12/SC-13, ISO 27001 8.24 -- also carries FIPS validation status/certificate number/module name (added 2026-09-24) for CR26's Cryptographic Modules review |
| `bundles/system-interconnection-register.rain` | System Interconnection asset type | CA-3 |
| `bundles/contractor-access-register.rain` | Contractor Access asset type | PS-7 (individual level, distinct from the Subprocessor Register's company level) |
| `bundles/data-inventory-register.rain` | Data Asset type | RA-2, ISO 27001 5.12/5.13 |
| `bundles/software-inventory-register.rain` | Software Component asset type | CR26 Inventory/SBOM -- one row per in-scope component, container image, package, or dependency. Distinct from the Software License Register above, which tracks the vendor agreement, not the running software itself. |
| `bundles/conmon-submission-register.rain` | ConMon Submission asset type | CR26 Collaborative Continuous Monitoring -- one row per monthly package delivered to FedRAMP and authorized agency customers |
| `bundles/six-sigma-infraction-register.rain` | Six Sigma Infraction asset type | ISO 9001:2015 Clause 10.2 (Nonconformity and Corrective Action) -- one row per process defect or out-of-control condition, tracked with DMAIC phase, Ishikawa root-cause category, DPMO/sigma-level impact, cost of poor quality, and corrective/preventive action. A quality-management register, not a security/privacy one -- the one template here that isn't FedRAMP/NIST/PCI/ISO 27001-driven. |
| `bundles/poam-tracking-fields.rain` | *Ticket* fields | CA-5 (POA&M) |
| `bundles/vulnerability-scan-finding-fields.rain` | *Ticket* fields | RA-5/RA-7 -- optional; Tickets > Import reads a Nessus `.nessus` file, an OpenVAS/GVM XML export, or an Amazon Inspector JSON findings report natively, from any of the three, with the same vendor-neutral field labels (Scanner check ID/Check name/Check family cover a Nessus plugin, an OpenVAS/GVM NVT, or an Inspector CVE/finding type either way) |
| `bundles/fedramp-ocr-fields.rain` | *Ticket* fields | FedRAMP CR26's Ongoing Certification Report -- additive alongside the POA&M template, not a replacement for it (see `docs/itsm-controls-mapping.md`'s CA-5 entry) |
| `bundles/fedramp-ver-fields.rain` | *Ticket* fields | FedRAMP's Vulnerability Evaluation and Reporting activity (VER-RPT-VDT/VER-RPT-AVI/VER-TFR-MRH) -- N-rating, IRV/LEV classification, PAIN reduction history, and final disposition on Vulnerability tickets. Pairs with `fedramp-ocr-fields.rain`'s own "Accepted vulnerability (OCR)" flag (reused here, not duplicated) to split a vulnerability between the two report shapes. |
| `bundles/fedramp-incident-report-fields.rain` | *Ticket* fields | FedRAMP's unified Incident Report (IEC-CSO-IIR/OIR/FIR) on Incident tickets -- one set of fields covers all three report types in the lifecycle, "FedRAMP report type" names which one a given export represents. |
| `bundles/fedramp-certification-package.rain` | FedRAMP Certification Package asset type | Mirrors fedramp.gov's Certification Package Overview schema (2026-06-24) -- CSP/service-identity metadata for a tenant that's itself a FedRAMP-certified CSP. Also carries FIPS 199 impact and an authorization boundary description for the OSCAL recipe below -- those two aren't part of the marketplace schema. |
| `bundles/fedramp-package-contacts.rain` | FedRAMP Package Contact asset type | The same schema's repeating `contactInformation` array -- pairs with `fedramp-certification-package.rain` |
| `bundles/fedramp-package-repositories.rain` | FedRAMP Package Repository asset type | The same schema's `trustCenter`/`secureConfigurationGuidance`/`additionalRepositories` -- pairs with `fedramp-certification-package.rain` |
| `bundles/security-control-register.rain` | Security Control asset type | Any control catalog (NIST 800-53, ISO 27001 Annex A, SOC 2, CMMC, ...) -- one row per control implementation statement, plus Last Assessment Date/Last Assessment Result/Assessor for recording assessment outcomes directly on the row they apply to. Pairs with `oscal-control-implementation.jq`, below, which exports this register as an OSCAL control-implementation fragment, and with `assessment-register.rain` for tracking the assessment engagements themselves. |
| `bundles/assessment-register.rain` | Assessment asset type | A cover record per assessment/audit engagement (self-assessment, 3PAO assessment, internal audit, ...) -- scope, assessor, planned/completion dates, status, overall result, findings summary. Per-control results live on `security-control-register.rain`'s own rows, not here -- re-import that register's CSV with Last Assessment Date/Result/Assessor updated for the controls this engagement actually covered. |
| `bundles/oscal-ssp-starter-kit.rain` | 3 asset types + 3 export profiles + 1 export recipe | Everything for the OSCAL System Security Plan recipe below, in one import. |
| `bundles/oscal-ssp-export-recipe.rain` | 3 export profiles + 1 export recipe | Same recipe, no asset types -- for a tenant that already has the three registers it needs. |
| `bundles/case-management-fields.rain` | *Ticket* fields | Adds Subject/responsible party, Suspected violation type, Investigation status, Findings, and Disposition/consequence to Incident tickets -- for the "investigate a suspected non-compliance, determine who's responsible and what happens next" shape, distinct from a plain security-incident response (same Incident ticket type, just a different set of fields in play for this kind of case). Note: ticket visibility in RAIN is tenant-wide by role, not per-ticket -- this doesn't add confidentiality/restricted-access for a sensitive investigation, only the data fields. |
| `data/nist-800-53-rev5-low.csv` / `-moderate.csv` / `-high.csv` | *Asset data*, not config | The real FedRAMP Rev 5 Low/Moderate/High baselines (424/688/791 rows), one per FedRAMP "response-point" -- an Assets > Import file, not a Config Bundle; pairs with `security-control-register.rain` above. Generated by `data/extract_fedramp_baseline.py` -- rerun it against a future baseline update to regenerate these. |
| `data/iso-27001-2022-annex-a-controls.csv` | *Asset data*, not config | All 93 ISO/IEC 27001:2022 Annex A controls (37 Organisational, 8 People, 14 Physical, 34 Technological) -- same shape as the NIST CSVs above (Statement ID always blank; ISO has no lettered sub-statement breakdown), pairs with `security-control-register.rain`. Generated by `data/extract_iso27001_controls.py` from Hightable's free control list. |
| `data/soc2-type2-controls.csv` | *Asset data*, not config | All 60 SOC 2 Type II controls across every Trust Services Criteria (Security/Common Criteria, Availability, Confidentiality, Processing Integrity, Privacy) -- same shape again (Statement ID always blank; SOC 2 has no lettered sub-statement breakdown), pairs with `security-control-register.rain`. Generated by `data/extract_soc2_controls.py` from SecureSlate's free control list. |
| `data/extract_c5_controls.py` | *Script*, no data checked in | Turns BSI's C5:2026 machine-readable YAML into the same CSV shape as the three kits above (629 rows: one per Basic/Additional-Sharpen/Additional-Complement sub-criterion, plus the flat General Conditions). No `c5-*.csv` ships in this repo -- the catalogue is CC BY-ND (No Derivatives) licensed, which withholds permission to distribute an adapted version of the work; generating one for your own tenant is fine, this repo redistributing one on your behalf isn't. Run the script yourself against your own downloaded copy -- see its own docstring. |
| `data/extract_ccm_controls.py` | *Script*, no data checked in | Turns the Cloud Security Alliance's Cloud Controls Matrix into the same CSV shape, for CSA STAR certification directly and as the base register for Singapore government cloud work via MTCS SS 584 (see the script's own docstring for how the two relate). Same script-only treatment as C5 above, for the same reason: CSA requires a license the moment you customize or embed the CCM, and MTCS SS 584 is a paid Singapore Standard that holds its control text privately. Every other extractor here was built against a verified real copy of its source; this one wasn't, since CSA's download is account-gated. Its column matching is deliberately loose and prints exactly what it couldn't find if your file's headers differ. |
| `data/cmmc-level-1-controls.csv` | *Asset data*, not config | All 17 CMMC Level 1 practices (FAR 52.204-21(b)'s 15 basic safeguarding requirements for Federal Contract Information) -- same shape again (Statement ID always blank), pairs with `security-control-register.rain`. Generated by `data/extract_cmmc_level1.py` from the CMMC Self-Assessment Guide -- Level 1, Version 2.0. |
| `data/cmmc-level-2-controls.csv` | *Asset data*, not config | All 110 CMMC Level 2 practices -- NIST SP 800-171 Rev 2's own security requirements verbatim, relabeled with their CMMC `DD.L2-` practice IDs. Generated by `data/extract_cmmc_level2.py` from NIST's own official security-requirements CSV export. |
| `data/cmmc-level-3-controls.csv` | *Asset data*, not config | All 24 additional CMMC Level 3 practices -- DoD's own curated subset of NIST SP 800-172's enhanced security requirements, per Table 1 to 32 CFR 170.14(c)(4) (practice IDs carry the model's own `e` suffix, e.g. `AC.L3-3.1.2e`). Layer on top of Level 2's 110 for the full Level 3 set (134 total) -- Level 3 has no practices of its own below that. Generated by `data/extract_cmmc_level3.py` from eCFR's own versioner API. |
| `bundles/fedramp-scn-fields.rain` | *Ticket* fields | Mirrors fedramp.gov's Significant Change Notification schema (2026-06-24) -- an SCN is structurally a Change ticket's own metadata (what changed, why, the plan and timeline), so this adds fields to Change tickets rather than a new asset type. Pairs with `fedramp-scn-export.jq`, below. |
| `bundles/fedramp-ksi-starter-kit.rain` | Key Security Indicator asset type (+ its own copy of Security Control) + 2 export profiles + 1 export recipe | Everything for the FedRAMP Security Decision Record recipe below, in one import. |
| `bundles/fedramp-ksi-export-recipe.rain` | 2 export profiles + 1 export recipe | Same recipe, no asset types -- for a tenant that already has both registers it needs. |
| `data/fedramp-20x-key-security-indicators.csv` | *Asset data*, not config | All 46 real FedRAMP 20x Key Security Indicators across 10 families, published directly by FedRAMP as machine-readable data -- pairs with `fedramp-ksi-starter-kit.rain` above. Generated by `data/extract_fedramp_ksi.py` -- rerun it against a future KSI revision to regenerate this. |

Everything except the four ticket-scoped ones (POA&M, Nessus, FedRAMP
OCR, FedRAMP SCN) seeds an asset type plus its fields; those four seed
tenant-wide ticket custom fields instead, since that data tracks a
ticket's own lifecycle, not a persistent asset's.

The three FedRAMP Package templates are also referenced from
`subprocessor-register.rain`, which picked up three additional fields
(2026-09-14) for a FedRAMP-certified CSP's own third-party resources
(the same schema's `thirdPartyInformationResources`) -- additive to
that template, not a new one, since it's the same vendor-plus-use-case
shape the register already tracks.

## Why these

Each one closes a specific gap `docs/itsm-controls-mapping.md` and
`docs/eucs-compliance-assessment.md` identify against real frameworks
(FedRAMP/NIST 800-53, PCI-DSS, ISO 27001, EUCS) -- picked because
they're common enough that most compliance-minded tenants would
otherwise build the same custom asset type or field set by hand. None
of them are required for RAIN to work; they're a five-minute head
start, not a dependency.

`software-inventory-register.rain` and `conmon-submission-register.rain`
(new 2026-09-24), plus the FIPS fields added to
`encryption-key-cert-register.rain` the same day, close three specific
gaps identified against FedRAMP CR26's own published areas of review --
see [`docs/cr26-coverage-showcase.md`](../cr26-coverage-showcase.md)
for how all three actually work in RAIN, against real data.

The three FedRAMP Package templates are the one exception to "most
compliance-minded tenants" -- they only make sense for a tenant that's
itself a FedRAMP-certified cloud service provider preparing or
maintaining its own certification package, not for an agency or any
other tenant tracking compliance against a framework generally.

**Don't see your framework?** These aren't the only ones that'll ever
exist -- if you're working against a program we haven't covered (a
different national framework, an industry-specific one, whatever), say
so and we'll put one together.

## Using one

Admin > Config Bundles > Tenant > Import, pick the file from `bundles/`.
Each only carries `custom_fields` (and, for the asset-scoped ones,
`asset_types`) -- nothing else already configured (tickets, webhooks,
groups, users) is touched. Rename, add, or drop fields afterward the
same as anything you'd built yourself: Admin > Asset Types, or Tickets
> Custom Fields for the four ticket-scoped templates.

A template's `source_tenant_slug`/`source_tenant_name` are just export
provenance -- never read on import. A bundle always imports into
whichever tenant your session currently has active; it can't create a
new tenant or target a different one.

## FedRAMP document exports

RAIN's own tracked data (Security Control rows, Change/Incident/
Vulnerability tickets) already covers most of what FedRAMP's own
submission schemas ask for. Everything below turns that tracked data
into the real `fedramp-*-schema-2026-06-24.json` document, instead of
re-typing it into FedRAMP's own format by hand. Most run through the
Tickets/Assets JSON export's optional jq "transform" step (see the
"Export" sections of `docs/user-guide.md`); a document assembled from
more than one source (the OSCAL SSP, the Security Decision Record)
uses an Export Recipe instead, which merges several exports into one.

A transformer with its own per-CSP constants at the top (a
certification package URI, a reporting period, ...) needs them filled
in once -- see the file's own header comment. A schema-required field
a transformer can't derive from tracked data comes out as an empty
placeholder rather than an invented value, so the output stays valid
JSON either way, just not finished until filled in by hand.

### OSCAL control-implementation fragment

`transforms/oscal-control-implementation.jq` turns the Security
Control register into an OSCAL `control-implementation` fragment, not
a full `system-security-plan` -- metadata, system-characteristics, and
system-implementation come from the Export Recipe below instead. Start
from a real baseline rather than a blank register: the NIST Rev 5,
ISO 27001, SOC 2, and CMMC CSVs above all pair with this register
directly; C5 and CSA STAR/MTCS need their own extractor script run
against a licensed download first.

Full walkthrough: [`docs/oscal-ssp-showcase.md`](../oscal-ssp-showcase.md).

### Export Recipes and the OSCAL System Security Plan

A full SSP needs three sources merged -- system characteristics,
components, and control implementation -- more than one export's jq
filter can produce alone. `bundles/oscal-ssp-starter-kit.rain` seeds
everything needed in one import; `bundles/oscal-ssp-export-recipe.rain`
is the same recipe for a tenant that already has those asset types.
Recipe filters attach as Documents after import, same as everywhere
else in Config Bundles -- they're data, not config.

Full walkthrough: [`docs/oscal-ssp-showcase.md`](../oscal-ssp-showcase.md),
section 5.

### Tracking assessments

A light-touch assessment/audit cycle against the Security Control
register, without a dedicated assessment engine: `bundles/assessment-
register.rain` holds one row per engagement (scope, assessor, dates,
overall result); the per-control outcome lives back on the Security
Control register's own Last Assessment Date/Result/Assessor fields,
updated via the same CSV re-import used to seed the register in the
first place. Anything that comes back "Other Than Satisfied" is a
finding -- file a ticket for it and link it back to the asset.

### Significant Change Notification export

`transforms/fedramp-scn-export.jq` turns a Change ticket's own fields
(`bundles/fedramp-scn-fields.rain`) into a FedRAMP Significant Change
Notification -- an SCN is structurally change metadata, so this adds
fields to Change tickets rather than a new asset type.

Full worked example, including the real captured export:
[`docs/fedramp-cr26-showcase.md`](../fedramp-cr26-showcase.md).

### Vulnerability Evaluation and Reporting (VER) exports

Three transformers share one set of ticket fields
(`bundles/fedramp-ver-fields.rain`): `fedramp-vdt-export.jq` and
`fedramp-avi-export.jq` split non-accepted vs. accepted findings for a
reporting period, `fedramp-historical-ver-export.jq` covers every
current finding with no period. Which transformer a finding belongs in
is decided by `fedramp-ocr-fields.rain`'s own "Accepted vulnerability"
flag, not a separate field.

### Incident Report export

`transforms/fedramp-incident-report-export.jq` turns Incident tickets
(`bundles/fedramp-incident-report-fields.rain`) into FedRAMP Incident
Reports. One schema covers all three stages of the IEC-CSO lifecycle
(Initial/Ongoing/Final) -- a ticket's own "FedRAMP report type" field
names which stage a given export represents, flipped by hand as the
incident progresses.

### Ongoing Certification Report export

An Ongoing Certification Report is mostly narrative, not ticket data.
`transforms/fedramp-ocr-export.jq` fills in what tickets do know
(accepted vulnerabilities, transformative changes, reportable
incidents) and leaves the quarterly-summary sections as empty-but-valid
placeholders, written by hand each quarter.

### Certification Package Overview export

Three asset types (`bundles/fedramp-certification-package.rain`,
`-package-contacts.rain`, `-package-repositories.rain`) and three
matching transformers assemble fedramp.gov's own Certification Package
Overview schema -- CSP identity, contacts, and repositories/Trust
Center links. An Export Recipe with no assembly filter runs all three
in one step instead of hand-assembling the pieces.

### Security Decision Record export

`transforms/fedramp-security-decision-record-export.jq` exports the
Security Control register as the `securityControls[]` section of a
FedRAMP Security Decision Record. `keySecurityIndicators` has real
coverage too now -- the next section covers the complete-document path.

## FedRAMP 20x Key Security Indicators

FedRAMP 20x measures a cloud service offering against 46 Key Security
Indicators (KSIs) across 10 families -- Cybersecurity Education,
Change Management, Cloud Native Architecture, Identity and Access
Management, Incident Response, Monitoring/Logging/Auditing, Policy and
Inventory, Recovery Planning, Supply Chain Risk, and Service
Configuration. Each KSI is a real, currently-published requirement
with its own ID (e.g. `KSI-CNA-DFP`), published by FedRAMP itself as
machine-readable data at
[`github.com/FedRAMP/rules`](https://github.com/FedRAMP/rules)'
`fedramp-consolidated-rules.json` -- a U.S. government work, so unlike
the CCM/MTCS kit above, this one ships as a real, ready CSV rather
than a script-only extractor.

`bundles/fedramp-ksi-starter-kit.rain` seeds a Key Security Indicator
asset type alongside its own copy of the Security Control asset type,
so it works standalone even without `security-control-register.rain`
already imported. `bundles/fedramp-ksi-export-recipe.rain` is the
narrower version (profiles and recipe only) for a tenant that already
has both registers. `data/fedramp-20x-key-security-indicators.csv`
carries the real 46 indicators, ready to import instead of starting
from a blank register.

This fills in the one section the Security Decision Record transform
has always left as an empty placeholder: import the starter kit, fill
in Implementation Status/Narrative/Validation/Assessment/Tests/
Evidence per indicator, then run the Export Recipe with destination
"Save to a Document" and Trust Center flagged -- that publishes the
result at the tenant's own Trust Center tab immediately, no separate
export-then-upload step.

A KSI landing on `Partially Implemented` or `Not Implemented` is a
finding -- file a Vulnerability (or Incident) ticket for it the normal
way and link it back to the Key Security Indicator asset, same pattern
"Tracking assessments" above already uses for a Security Control row
that comes back `Other Than Satisfied`. A KSI whose own statement says
"persistently" (continuous, automated evidence) is a good fit for a
recurring Calendar entry as the re-validation reminder, the same
pattern [`docs/drift-detection-showcase.md`](../drift-detection-showcase.md)
already uses for its own weekly check. See
[`docs/fedramp-ksi-showcase.md`](../fedramp-ksi-showcase.md) for the
full walkthrough against real indicator data.
