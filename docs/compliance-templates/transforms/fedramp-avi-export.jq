# fedramp-avi-export.jq
#
# Turns a Tickets JSON export (Type = vulnerability, with the fields
# from fedramp-ver-fields.rain, fedramp-ocr-fields.rain's "Accepted
# vulnerability (OCR)"/"Acceptance justification" fields, selected)
# into a FedRAMP Accepted Vulnerability Info report (VER-RPT-AVI) --
# one object per vulnerability ticket flagged "Accepted vulnerability
# (OCR)" with activity in the report period, valid against
# fedramp-accepted-vulnerability-info-schema-2026-06-24.json. Rows
# whose Type isn't "vulnerability", or that aren't flagged accepted,
# are skipped -- those belong in VER-RPT-VDT instead
# (fedramp-vdt-export.jq), not duplicated here.
#
# EDIT THIS BEFORE USE: see fedramp-vdt-export.jq's own header -- same
# three constants, same reasoning.
#
# Column expectations and the boolean-field note are also identical to
# fedramp-vdt-export.jq; see that file's own header.

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
    "acceptedVulnerabilities": [
      .[]
      | select((.["Type"] // "" | ascii_downcase) == "vulnerability")
      | select(.["Accepted vulnerability (OCR)"] | boolish)
      | {"vulnerabilityDetail": vulnerability_detail}
        + (if (.["Acceptance justification"] // "" | present)
           then {"acceptanceRationale": .["Acceptance justification"]} else {} end)
    ]
  }
  + (if (certification_package_overview_uri | present)
     then {"certificationPackageOverviewUri": certification_package_overview_uri} else {} end)
  + (if ($period | length) > 0 then {"reportPeriod": $period} else {} end)
