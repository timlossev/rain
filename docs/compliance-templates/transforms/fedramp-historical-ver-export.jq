# fedramp-historical-ver-export.jq
#
# Turns a Tickets JSON export (Type = vulnerability, with the fields
# from fedramp-ver-fields.rain, fedramp-ocr-fields.rain's "Accepted
# vulnerability (OCR)"/"Acceptance justification" fields, selected)
# into a FedRAMP Historical VER Activity snapshot (VER-TFR-MRH) -- every
# current vulnerability ticket, active and accepted alike, split into
# the two arrays that schema wants, valid against
# fedramp-historical-ver-activity-schema-2026-06-24.json. Unlike
# fedramp-vdt-export.jq/fedramp-avi-export.jq, this isn't scoped to a
# report period -- it's a full current-state snapshot, so export every
# open vulnerability ticket (no status filter) rather than only ones
# with activity since a given date.
#
# EDIT THIS BEFORE USE: certification_package_overview_uri is a
# per-CSP constant -- same reasoning as fedramp-vdt-export.jq's own
# header. generatedAt is computed automatically (the time this filter
# actually runs), not something to fill in.
#
# Column expectations and the boolean-field note are identical to
# fedramp-vdt-export.jq; see that file's own header.

def certification_package_overview_uri: "";

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

[.[] | select((.["Type"] // "" | ascii_downcase) == "vulnerability")] as $vulns
| {
    "generatedAt": (now | todate),
    "activeVulnerabilities": [
      $vulns[] | select((.["Accepted vulnerability (OCR)"] | boolish) | not) | vulnerability_detail
    ],
    "acceptedVulnerabilities": [
      $vulns[]
      | select(.["Accepted vulnerability (OCR)"] | boolish)
      | {"vulnerabilityDetail": vulnerability_detail}
        + (if (.["Acceptance justification"] // "" | present)
           then {"acceptanceRationale": .["Acceptance justification"]} else {} end)
    ]
  }
  + (if (certification_package_overview_uri | present)
     then {"certificationPackageOverviewUri": certification_package_overview_uri} else {} end)
