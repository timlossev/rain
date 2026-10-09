# fedramp-incident-report-export.jq
#
# Turns a Tickets JSON export (Type = incident, with the fields from
# fedramp-incident-report-fields.rain selected) into an array of FedRAMP
# Incident Reports -- one object per incident ticket, each independently
# valid against fedramp-incident-report-schema-2026-06-24.json. Rows
# whose Type isn't "incident" are silently skipped, so it's safe to run
# against a broader export by mistake. One ticket covers all three
# report types in the IEC-CSO lifecycle (Initial/Ongoing/Final) over its
# life -- "FedRAMP report type" names which one THIS export represents,
# flipped by hand as the incident progresses; Final additionally needs
# "Resolved at" filled in (the schema requires it when reportType is
# Final, not enforced here -- this transformer omits whatever's blank
# rather than inventing a placeholder, same as every other transform in
# this directory).
#
# EDIT THIS BEFORE USE: certification_package_overview_uri below is a
# per-CSP constant -- see fedramp-scn-export.jq's own header for the
# same reasoning.
#
# Expects the export's column headers to match
# fedramp-incident-report-fields.rain's own custom field labels exactly
# (the default when you don't rename them on the export screen), plus
# the ticket exporter's own built-in "Number"/"Title"/"Description"
# columns.

def certification_package_overview_uri: "";

def present: . != null and (. | tostring | length) > 0;

def list_from(text):
  if (text | present) then
    text | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(present))
  else [] end;

def milestones_from(text):
  if (text | present) then
    text
    | split(";")
    | map(select(present))
    | map(
        (split("|") | map(gsub("^\\s+|\\s+$"; ""))) as $parts
        | {"milestoneDescription": ($parts[0] // "")}
        + (if ($parts[1]? // "" | present) then {"occurredAt": $parts[1]} else {} end)
      )
  else [] end;

map(select((.["Type"] // "" | ascii_downcase) == "incident"))
| map(
    (
      (list_from(.["Historical N-ratings (comma-separated)"])) as $historical
      | (if ($historical | length) > 0 then {"historicalRating": ($historical | map(tonumber))} else {} end)
      + (if (.["Current Potential Agency Impact (N-rating)"] // "" | present)
         then {"currentRating": (.["Current Potential Agency Impact (N-rating)"] | tonumber)} else {} end)
      + (if (.["PAIN evaluation notes"] // "" | present)
         then {"evaluationNotes": .["PAIN evaluation notes"]} else {} end)
    ) as $potentialImpact
    | (
        (if (.["Incident started at"] // "" | present) then {"startedAt": .["Incident started at"]} else {} end)
        + (if (.["Incident detected at"] // "" | present)
           then {"detectedAt": .["Incident detected at"]} else {} end)
        + (if (.["Detection source"] // "" | present)
           then {"detectionSource": .["Detection source"]} else {} end)
        + (if (.["Reportable incident evaluation completed at"] // "" | present)
           then {"evaluationCompletedAt": .["Reportable incident evaluation completed at"]} else {} end)
        + (
            (milestones_from(.["Incident milestones (semicolon-separated: description | YYYY-MM-DD; description | YYYY-MM-DD)"])) as $m
            | if ($m | length) > 0 then {"milestones": $m} else {} end
          )
      ) as $timeline
    | {
        "providerTrackingId": (.["Number"] // "")
      }
      + (if (certification_package_overview_uri | present)
         then {"certificationPackageOverviewUri": certification_package_overview_uri} else {} end)
      + (if (.["FedRAMP report type"] // "" | present) then {"reportType": .["FedRAMP report type"]} else {} end)
      + (if (.["Federal incident response coordinator"] // "" | present)
         then {"federalIncidentCoordinator": .["Federal incident response coordinator"]} else {} end)
      + (if (.["Description"] // "" | present) then {"incidentDescription": .["Description"]}
         elif (.["Title"] // "" | present) then {"incidentDescription": .["Title"]} else {} end)
      + (if ($timeline | length) > 0 then {"timeline": $timeline} else {} end)
      + (if ($potentialImpact | length) > 0 then {"potentialImpact": $potentialImpact} else {} end)
      + (if (.["Functional impact"] // "" | present) then {"functionalImpact": .["Functional impact"]} else {} end)
      + (if (.["Recovery plan"] // "" | present) then {"recoveryPlan": .["Recovery plan"]} else {} end)
      + (
          (list_from(.["Likely affected agencies (comma-separated)"])) as $agencies
          | if ($agencies | length) > 0 then {"affectedAgencies": $agencies} else {} end
        )
      + (if (.["Observed incident activity"] // "" | present)
         then {"observedActivity": .["Observed incident activity"]} else {} end)
      + (
          (list_from(.["Indicators of compromise (comma-separated)"])) as $iocs
          | if ($iocs | length) > 0 then {"indicatorsOfCompromise": $iocs} else {} end
        )
      + (
          (list_from(.["Related CVE identifiers (comma-separated)"])) as $cves
          | if ($cves | length) > 0 then {"relatedCveIds": $cves} else {} end
        )
      + (if (.["Root cause"] // "" | present) then {"rootCause": .["Root cause"]} else {} end)
      + (if (.["Response and recovery activities"] // "" | present)
         then {"responseAndRecoveryActivities": .["Response and recovery activities"]} else {} end)
      + (if (.["Resolved at (required for Final reports)"] // "" | present)
         then {"resolvedAt": .["Resolved at (required for Final reports)"]} else {} end)
  )
