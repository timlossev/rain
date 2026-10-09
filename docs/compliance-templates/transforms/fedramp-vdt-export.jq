# fedramp-vdt-export.jq
#
# Turns a Tickets JSON export (Type = vulnerability, with the fields
# from fedramp-ver-fields.rain and the "Accepted vulnerability (OCR)"
# field from fedramp-ocr-fields.rain selected) into a FedRAMP
# Vulnerability Detail Report (VER-RPT-VDT) -- one object per non-
# accepted vulnerability ticket with activity in the report period,
# valid against fedramp-vulnerability-detail-report-schema-2026-06-24.
# json. Rows whose Type isn't "vulnerability", or that are flagged
# "Accepted vulnerability (OCR)", are skipped -- those belong in
# VER-RPT-AVI instead (fedramp-avi-export.jq), not duplicated here.
#
# EDIT THIS BEFORE USE: the three defs below are constants, not per-row
# data -- fill them in once rather than re-typing them on every export.
# certification_package_overview_uri and the report period are both
# required by the schema; left blank, this transformer omits the key
# rather than inventing a placeholder, which will fail validation until
# filled in.
#
# Expects the export's column headers to match fedramp-ver-fields.rain's
# own custom field labels exactly (the default when you don't rename
# them on the export screen), plus the ticket exporter's own built-in
# "Number"/"Title"/"Description"/"Created" columns and
# fedramp-ocr-fields.rain's "Accepted vulnerability (OCR)" field. A
# boolean custom field column comes through the JSON export as a real
# JSON true/false (or null if never set), not the string "true" --
# boolish below accepts that shape and a plain-text "true"/"1"/"yes"
# alike, in case this is re-run against a CSV round-trip instead.

def certification_package_overview_uri: "";
def report_period_from: ""; # e.g. "2026-07-01T00:00:00Z"
def report_period_to: "";   # e.g. "2026-09-30T23:59:59Z"

def present: . != null and (. | tostring | length) > 0;
def boolish: . == true or . == "true" or . == "1" or (. == "yes" or . == "Yes");

def pain_events_from(text):
  if (text | present) then
    text
    | split(";")
    | map(select(present))
    | map(
        (split("|") | map(gsub("^\\s+|\\s+$"; ""))) as $parts
        | {"reducedAt": ($parts[0] // "")}
        + (if ($parts[1]? // "" | present) then {"rating": ($parts[1] | tonumber)} else {} end)
      )
  else [] end;

def vulnerability_detail:
  (
    (if (.["Projected next PAIN reduction date"] // "" | present)
     then {"estimatedAt": .["Projected next PAIN reduction date"]} else {} end)
    + (if (.["Projected next PAIN reduction target rating"] // "" | present)
       then {"targetRating": (.["Projected next PAIN reduction target rating"] | tonumber)} else {} end)
  ) as $projected
  | (
    (if (.["Is overdue (VER-TFR)"] != null)
     then {"isOverdue": (.["Is overdue (VER-TFR)"] | boolish)} else {} end)
    + (if (.["Overdue explanation"] // "" | present) then {"explanation": .["Overdue explanation"]} else {} end)
  ) as $overdue
  | (pain_events_from(.["PAIN reduction events (semicolon-separated: YYYY-MM-DD | rating; YYYY-MM-DD | rating)"])) as $events
  | {
      "providerTrackingId": (.["Number"] // ""),
      "detection": (
        {"detectedAt": (.["Created"] // "")}
        + (if (.["Detection source"] // "" | present) then {"detectionSource": .["Detection source"]} else {} end)
      ),
      "vulnerabilityDescription": (
        if (.["Description"] // "" | present) then .["Description"] else (.["Title"] // "") end
      )
    }
    + (if (.["Potential agency impact"] // "" | present)
       then {"potentialAgencyImpact": .["Potential agency impact"]} else {} end)
    + (if (.["Evaluation completed at"] // "" | present)
       then {"evaluationCompletedAt": .["Evaluation completed at"]} else {} end)
    + (if (.["Is internet-reachable (IRV)"] != null)
       then {"isInternetReachable": (.["Is internet-reachable (IRV)"] | boolish)} else {} end)
    + (if (.["Is likely exploitable (LEV)"] != null)
       then {"isLikelyExploitable": (.["Is likely exploitable (LEV)"] | boolish)} else {} end)
    + (if (.["Current Potential Agency Impact (N-rating)"] // "" | present)
       then {"currentRating": (.["Current Potential Agency Impact (N-rating)"] | tonumber)} else {} end)
    + (if ($projected | length) > 0 then {"projectedNextReduction": $projected} else {} end)
    + (if ($overdue | length) > 0 then {"overdueStatus": $overdue} else {} end)
    + (if (.["Supplementary risk information"] // "" | present)
       then {"supplementaryRiskInformation": .["Supplementary risk information"]} else {} end)
    + (if ($events | length) > 0 then {"painReductionEvents": $events} else {} end)
    + (if (.["Final disposition"] // "" | present) then {"finalDisposition": .["Final disposition"]} else {} end);

(
  (if (report_period_from | present) then {"from": report_period_from} else {} end)
  + (if (report_period_to | present) then {"to": report_period_to} else {} end)
) as $period
| {
    "vulnerabilities": [
      .[]
      | select((.["Type"] // "" | ascii_downcase) == "vulnerability")
      | select((.["Accepted vulnerability (OCR)"] | boolish) | not)
      | vulnerability_detail
    ]
  }
  + (if (certification_package_overview_uri | present)
     then {"certificationPackageOverviewUri": certification_package_overview_uri} else {} end)
  + (if ($period | length) > 0 then {"reportPeriod": $period} else {} end)
