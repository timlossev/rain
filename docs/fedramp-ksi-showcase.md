# FedRAMP 20x KSI showcase: a real Security Decision Record

FedRAMP 20x's continuous-assessment model asks a CSP to answer, for
each of the 46 real published Key Security Indicators, what's
actually implemented and how it's validated -- structured evidence,
not a one-time audit narrative. This walks through doing that in
RAIN against the real indicator set, real narrative answers, and the
actual exported Security Decision Record: validated against FedRAMP's
own schema, published to a live Trust Center, and fetched back
signed out, with no login at all. Nothing here is mocked up; every
JSON block below is the real captured output.

See [`docs/compliance-templates/README.md`](compliance-templates/README.md#fedramp-20x-key-security-indicators)
for the underlying bundles and transforms.

## 1. Seed the register

`docs/compliance-templates/bundles/fedramp-ksi-starter-kit.rain` seeds
a Key Security Indicator asset type and its own copy of Security
Control, plus the two export profiles and the recipe tying them
together. `docs/compliance-templates/data/fedramp-20x-key-security-
indicators.csv` carries the real 46 indicators, published by FedRAMP
itself -- importing it lands all 46, across all 10 families, with
`Control Question` holding the actual published requirement text and
`Related Controls` holding each indicator's own NIST 800-53
cross-references.

## 2. Answer a few indicators

Three real rows, picked from three different families, show the
range an answer can take:

**KSI-CNA-DFP** (Cloud Native Architecture -- "The functionality and
privileges for infrastructure and services are strictly defined."),
**Implemented**:

- Narrative: *"Each workload runs under an IAM role scoped to only
  the AWS actions it needs; least-privilege policies are reviewed
  quarterly and enforced by SCPs that block broader grants at the org
  level."*
- Tests: quarterly least-privilege policy review; an automated AWS
  Config conformance scan, daily.
- Evidence: a Report, "AWS Config conformance pack results export,
  Q4 2026," with a Trust-Center-shareable location URL.

**KSI-IAM-AAM** (Identity and Access Management -- "The lifecycle and
privileges of all accounts, roles, and groups are securely managed
using automation."), **Partially Implemented**:

- Narrative: *"Human user account provisioning and deprovisioning is
  automated through the identity provider on hire/termination.
  Service account and role lifecycle management is still a manual
  ticket-driven process pending the Q1 2027 automation rollout."*
- A partial answer is still a real, exportable answer -- the point of
  structured evidence over a pass/fail audit narrative is that this
  gap is now visible and trackable, not hidden inside a paragraph.

**KSI-MLA-RVL** (Monitoring, Logging, and Auditing -- "Logs are
persistently reviewed and audited."), **Not Implemented**:

- Narrative: *"Logs are currently retained and searchable, but there
  is no standing review cadence -- logs are only pulled on an
  as-needed basis during an active investigation."*
- Assessment: *"Internal review, 2026-10-14: no recurring review in
  place; tracked as finding VULN-00042."*

That last one is the pattern `docs/compliance-templates/README.md`'s
"Tracking assessments" section already describes for a failed
Security Control row: a KSI that comes back `Not Implemented` is a
finding, filed as a Vulnerability ticket and linked back to the asset
-- the Assessment field above names the finding ticket directly, the
same way a real CSP's own tracking would.

The other 43 indicators in this example tenant are still blank, same
as a freshly imported register -- the next section shows exactly what
that looks like in the export, next to the three answered above.

## 3. Run the Export Recipe

`fedramp-ksi-starter-kit.rain` also seeds the recipe itself (two
steps, `controls` and `ksis`, each over its own export profile). Its
filters attach as Documents after import, same as every other recipe
in this directory -- `fedramp-security-decision-record-export.jq` on
the `controls` step (its own `certification_package_overview_uri`/
`metadata_version`/`metadata_update_source` constants edited in once),
`fedramp-ksi-export.jq` on the `ksis` step, and `fedramp-ksi-sdr-
assembly.jq` as the assembly filter. Destination: "Save to a
Document," Trust Center flagged.

Running it against this tenant's 791-row Security Control baseline
(the same FedRAMP Rev 5 High register [`docs/oscal-ssp-
showcase.md`](oscal-ssp-showcase.md) populates) and the 46-row KSI
register above produced a 44KB document. The three answered
indicators, captured exactly as exported:

```json
{
  "ksiId": "KSI-CNA-DFP",
  "ksiImplementationStatus": "Implemented",
  "ksiImplementation": [
    "Each workload runs under an IAM role scoped to only the AWS actions it needs; least-privilege policies are reviewed quarterly and enforced by SCPs that block broader grants at the org level."
  ],
  "ksiValidation": [
    "AWS Config conformance pack flags any IAM policy exceeding its workload baseline; findings route to a Vulnerability ticket."
  ],
  "ksiAssessment": [
    "Internal review, 2026-10-14: all 42 production roles conform to their workload baseline, zero exceptions open."
  ],
  "ksiTests": [
    "Quarterly least-privilege policy review",
    "Automated AWS Config conformance scan (daily)"
  ],
  "ksiEvidence": [
    {
      "evidenceType": "Report",
      "evidenceDescription": "AWS Config conformance pack results export, Q4 2026",
      "evidenceLocation": "https://trust.acme.example/evidence/cna-dfp-conformance-q4-2026"
    }
  ]
},
{
  "ksiId": "KSI-IAM-AAM",
  "ksiImplementationStatus": "Partially Implemented",
  "ksiImplementation": [
    "Human user account provisioning and deprovisioning is automated through the identity provider on hire/termination. Service account and role lifecycle management is still a manual ticket-driven process pending the Q1 2027 automation rollout."
  ],
  "ksiValidation": [
    "Identity provider SCIM sync logs confirm human accounts; service-account review is a manual quarterly audit today."
  ],
  "ksiAssessment": [
    "Internal review, 2026-10-02: 100% of human accounts automated, service accounts not yet automated."
  ],
  "ksiTests": [
    "Quarterly manual service-account audit"
  ],
  "ksiEvidence": [
    {
      "evidenceType": "Audit Record",
      "evidenceDescription": "Q3 2026 manual service-account review minutes"
    }
  ]
},
{
  "ksiId": "KSI-MLA-RVL",
  "ksiImplementationStatus": "Not Implemented",
  "ksiImplementation": [
    "Logs are currently retained and searchable, but there is no standing review cadence -- logs are only pulled on an as-needed basis during an active investigation."
  ],
  "ksiValidation": [],
  "ksiAssessment": [
    "Internal review, 2026-10-14: no recurring review in place; tracked as finding VULN-00042."
  ],
  "ksiTests": [],
  "ksiEvidence": []
}
```

And one of the 43 still-blank ones, unchanged from the register's own
default state -- exactly what an indicator nobody's answered yet looks
like in the export, same "present rather than invented" rule as
every other transformer in this directory:

```json
{
  "ksiId": "KSI-CED-RAT",
  "ksiImplementation": [],
  "ksiValidation": [],
  "ksiAssessment": [],
  "ksiTests": [],
  "ksiEvidence": []
}
```

`ksiTests` split correctly on the register's semicolon-separated
field into a real two-element array; `ksiEvidence` only appears where
an evidence field was actually filled in; `ksiImplementationStatus`
is left off entirely rather than written as an empty string, same
rule. `securityControls` carries all 791 rows through unchanged from
the existing, untouched `fedramp-security-decision-record-export.jq`
-- this recipe adds KSI coverage, it doesn't touch what already
worked.

## 4. Validate

Checked against the real downloaded
`fedramp-security-decision-record-schema-2026-06-24.json` (with its
external `$ref` to `fedramp-common-definitions-schema-2026-06-24.json`
resolved locally) using the `jsonschema` library, not reasoned about:

```
0 errors
```

The full document -- all 791 security controls, all 46 KSIs, three of
them answered -- validates cleanly as a single
`fedramp-security-decision-record-schema-2026-06-24.json` instance.

## 5. Trust Center

Trust Center flagged on the recipe means running it doesn't just
produce a Document -- it publishes one. Fetched with no session at
all, from the tenant's own public portal:

```
$ curl -s http://localhost:8000/portal/acme | grep -o 'FedRAMP Security Decision Record[^<]*'
FedRAMP Security Decision Record (Acme)
```

The listing carries its own preview and download links
(`/portal/acme/shared-documents/DOC-000018/preview` and
`/download`), the same signed-out preview-before-download flow every
other Trust Center document gets. Downloading it, still signed out,
returns the exact document validated above:

```
$ curl -s http://localhost:8000/portal/acme/shared-documents/DOC-000018/download
{"securityControls": [...791 entries...], "keySecurityIndicators": [...46 entries...], ...}
```

One Export Recipe run, with Trust Center already flagged, is the
entire path from "answered three KSIs" to "a FedRAMP-shaped document
sitting at a public URL a federal agency reviewer can hit directly" --
no separate export-then-upload step.

## Where this maps and where it doesn't

RAIN gets you: the 46-indicator register itself, straight from
FedRAMP's own published data; structured per-indicator evidence
instead of a narrative paragraph; the merge into one schema-valid
Security Decision Record; and the publish step, for free, from a flag
already on the recipe. It doesn't get you: the judgment call of what
"Implemented" actually means for a given indicator in your own
environment, or the underlying control work the KSI is asserting --
same as every other register in this directory, RAIN tracks the
answer, not the control itself.

A `Not Implemented` KSI is a finding -- file a Vulnerability (or
Incident) ticket and link it back, same as `KSI-MLA-RVL` above. A KSI
whose statement says "persistently" (continuous, automated evidence,
like `KSI-MLA-RVL`'s own review cadence once it exists) is a good fit
for a recurring Calendar entry as the re-validation reminder, the
same pattern [`docs/drift-detection-showcase.md`](drift-detection-showcase.md)
already uses for its own weekly check.
