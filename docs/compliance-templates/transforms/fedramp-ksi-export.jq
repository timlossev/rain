# fedramp-ksi-export.jq
#
# The "ksis" step of the FedRAMP Security Decision Record Export
# Recipe (see docs/compliance-templates/README.md). Turns a JSON
# export of the Key Security Indicator asset type
# (fedramp-ksi-starter-kit.rain) into a plain array shaped like
# fedramp-security-decision-record-schema-2026-06-24.json's own
# keySecurityIndicators[] -- one object per row.
#
# ksiTests is the schema's own array of strings; this register holds
# it as one semicolon-separated text field (same convention fedramp-
# scn-fields.rain's own Milestones field already uses for a list in
# one field), split back into an array here. ksiEvidence is the
# schema's own array of structured evidence objects; this register
# tracks one evidence item per row (Evidence Type/Description/
# Location), built into a single-element array here when any of the
# three is present, left out entirely otherwise -- multiple evidence
# items per indicator go through that asset's own Linked Documents
# instead of a second field for each one.
#
# Expects the export's column headers to match fedramp-ksi-starter-
# kit.rain's own custom field labels exactly.
#
# Used as an Export Recipe step's own filter -- its output is exactly
# the shape fedramp-ksi-sdr-assembly.jq expects under its "ksis" step.

def present: . != null and (. | tostring | length) > 0;

[
  .[]
  | {}
    + (if (.["Control ID"] // "" | present) then {"ksiId": .["Control ID"]} else {} end)
    + (if (.["Implementation Status"] // "" | present)
       then {"ksiImplementationStatus": .["Implementation Status"]} else {} end)
    + (if (.["Narrative"] // "" | present) then {"ksiImplementation": [.["Narrative"]]} else {"ksiImplementation": []} end)
    + (if (.["Validation"] // "" | present) then {"ksiValidation": [.["Validation"]]} else {"ksiValidation": []} end)
    + (if (.["Assessment"] // "" | present) then {"ksiAssessment": [.["Assessment"]]} else {"ksiAssessment": []} end)
    + {"ksiTests": (if (.["Tests"] // "" | present) then [.["Tests"] | split(";") | .[] | gsub("^\\s+|\\s+$"; "")] else [] end)}
    + (
        [
          {}
          + (if (.["Evidence Type"] // "" | present) then {"evidenceType": .["Evidence Type"]} else {} end)
          + (if (.["Evidence Description"] // "" | present) then {"evidenceDescription": .["Evidence Description"]} else {} end)
          + (if (.["Evidence Location"] // "" | present) then {"evidenceLocation": .["Evidence Location"]} else {} end)
        ] as $evidence
        | if ($evidence[0] | length) > 0 then {"ksiEvidence": $evidence} else {"ksiEvidence": []} end
      )
]
