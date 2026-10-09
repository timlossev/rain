# fedramp-ocr-export.jq
#
# Turns a Tickets JSON export (no Type filter -- vulnerability, incident,
# AND change tickets all need to be in the same export for this one to
# see all of them, with fedramp-ocr-fields.rain's three flag fields
# selected, plus fedramp-incident-report-fields.rain's fields if that
# template's also installed) into a FedRAMP Ongoing Certification Report
# skeleton (CCM-OCR-AVL), valid against
# fedramp-ongoing-certification-report-schema-2026-06-24.json.
#
# Unlike every other transform in this directory, an OCR isn't mostly
# ticket data -- four of its nine required top-level fields
# (certificationDataChanges, plannedCertificationDataChanges,
# updatedRecommendations, activeAgencies) are narrative/summary content
# nothing in a ticket tracker naturally produces, not an oversight here.
# This fills in what tickets DO know (accepted vulnerabilities,
# transformative changes, reportable incidents) and leaves the rest as
# present-but-empty placeholders -- a REQUIRED array with nothing to put
# in it is valid as `[]` (an empty `incidents` array already means
# exactly that per the schema's own reportableIncidents description:
# "attests that none occurred"), so this produces a schema-shaped
# skeleton either way, not something that fails validation just because
# a narrative section is still blank. Fill those sections in by hand
# before submitting -- this gets you most of the way there, not all of
# it.
#
# EDIT THIS BEFORE USE: every def below is a per-CSP/per-report-period
# constant, not per-row data -- fill in what applies once per quarter
# rather than hand-assembling the whole document from scratch.

def certification_package_overview_uri: "";
def report_period_from: "";          # e.g. "2026-07-01"
def report_period_to: "";            # e.g. "2026-09-30"
def planning_horizon_through: "";    # e.g. "2026-12-31" -- per the rule, at least 3 months past report_period_to
def certification_data_changes: "";       # semicolon-separated summary lines
def planned_certification_data_changes: ""; # semicolon-separated summary lines
def updated_recommendations: "";          # semicolon-separated summary lines
def active_agencies: "";                  # comma-separated agency names

def present: . != null and (. | tostring | length) > 0;
def boolish: . == true or . == "true" or . == "1" or (. == "yes" or . == "Yes");

def list_from(text):
  if (text | present) then
    text | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(present))
  else [] end;

def lines_from(text):
  if (text | present) then
    text | split(";") | map(gsub("^\\s+|\\s+$"; "")) | map(select(present))
  else [] end;

def incident_summary:
  (
    (.["Incident detected at"] // "" | select(present)) // (.["Created"] // "")
  ) as $occurred
  | {}
    + (if (.["Description"] // "" | present) then {"summary": .["Description"]}
       elif (.["Title"] // "" | present) then {"summary": .["Title"]} else {} end)
    + (if ($occurred | present) then {"occurredAt": $occurred} else {} end)
    + (if (.["Resolved at (required for Final reports)"] // "" | present)
       then {"resolvedAt": .["Resolved at (required for Final reports)"]} else {} end);

(
  (if (report_period_from | present) then {"from": report_period_from} else {} end)
  + (if (report_period_to | present) then {"to": report_period_to} else {} end)
) as $period
| (
  [.[] | select((.["Type"] // "" | ascii_downcase) == "vulnerability") | select(.["Accepted vulnerability (OCR)"] | boolish)]
) as $accepted_vulns
| (
  [.[] | select((.["Type"] // "" | ascii_downcase) == "change") | select(.["Transformative change"] | boolish)]
) as $transformative
| (
  [.[] | select((.["Type"] // "" | ascii_downcase) == "incident") | select(.["FedRAMP reportable incident"] | boolish)]
) as $reportable_incidents
| {
    "certificationDataChanges": lines_from(certification_data_changes),
    "plannedCertificationDataChanges": (
      {"changes": lines_from(planned_certification_data_changes)}
      + (if (planning_horizon_through | present)
         then {"planningHorizonThrough": planning_horizon_through} else {} end)
    ),
    "acceptedVulnerabilities": (
      if ($accepted_vulns | length) > 0 then
        $accepted_vulns
        | map((.["Number"] // "") + ": " + (.["Acceptance justification"] // .["Title"] // ""))
        | join("; ")
      else "" end
    ),
    "transformativeChanges": [$transformative[] | (.["Description"] // .["Title"] // "")],
    "updatedRecommendations": lines_from(updated_recommendations),
    "activeAgencies": list_from(active_agencies),
    "reportableIncidents": {"incidents": [$reportable_incidents[] | incident_summary]}
  }
  + (if (certification_package_overview_uri | present)
     then {"certificationPackageOverviewUri": certification_package_overview_uri} else {} end)
  + (if ($period | length) > 0 then {"reportPeriod": $period} else {} end)
