# fedramp-scn-export.jq
#
# Turns a Tickets JSON export (Type = change, with the fields from
# fedramp-scn-fields.rain selected) into an array of FedRAMP
# Significant Change Notifications -- one object per change ticket,
# each independently valid against
# fedramp-significant-change-notifications-schema-2026-06-24.json.
# Rows whose Type isn't "change" are silently skipped, so it's safe to
# run against a broader export by mistake.
#
# EDIT THIS BEFORE USE: certification_package_overview_uri below is a
# per-CSP constant (the URL of your own Certification Package Overview
# document), not per-change data -- fill it in once here rather than
# re-typing it on every change ticket. The schema requires it; if it's
# left blank, this transformer omits the key rather than inventing a
# placeholder, which will fail validation until you fill it in.
#
# Expects the export's column headers to match fedramp-scn-fields.rain's
# own custom field labels exactly (the default when you don't rename
# them on the export screen), plus the ticket exporter's own built-in
# "Type" and "Description"/"Title" columns.

def certification_package_overview_uri: "";

def present: . != null and (. | tostring | length) > 0;

# Both return [] (never jq's `empty`) when text is absent -- an object
# built as A + B + C ... produces NO output at all if any one of those
# terms evaluates to `empty` rather than a concrete value (confirmed
# the hard way building oscal-control-implementation.jq: it silently
# drops the whole surrounding object, not just that one key). []'s
# `length > 0` check downstream still comes out false either way, so
# nothing is lost by returning it instead.
def milestones_from(text):
  if (text | present) then
    text
    # Semicolon-, not newline-, separated: every RAIN custom field of
    # type "text" -- there's no distinct textarea type -- renders as a
    # single-line <input>, which silently can't hold an embedded
    # newline at all (confirmed live: a value typed/filled with \n
    # round-tripped through the field with the newlines simply gone).
    | split(";")
    | map(select(present))
    | map(
        (split("|") | map(gsub("^\\s+|\\s+$"; ""))) as $parts
        | {"milestoneDescription": ($parts[0] // "")}
        + (if ($parts[1]? // "" | present) then {"targetDate": $parts[1]} else {} end)
      )
  else [] end;

def list_from(text):
  if (text | present) then
    text | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(present))
  else [] end;

map(select((.["Type"] // "" | ascii_downcase) == "change"))
| map(
    {
      "changeDescription": (
        if (.["Description"] // "" | present) then .["Description"] else (.["Title"] // "") end
      )
    }
    + (if (certification_package_overview_uri | present)
       then {"certificationPackageOverviewUri": certification_package_overview_uri} else {} end)
    + (if (.["SCN change type"] // "" | present) then {"changeType": .["SCN change type"]} else {} end)
    + (if (.["SCN categorization explanation"] // "" | present)
       then {"changeTypeExplanation": .["SCN categorization explanation"]} else {} end)
    + (if (.["SCN reason for change"] // "" | present) then {"reason": .["SCN reason for change"]} else {} end)
    + (if (.["SCN customer impact"] // "" | present) then {"customerImpact": .["SCN customer impact"]} else {} end)
    + (if (.["SCN assessor name"] // "" | present) then {"assessorName": .["SCN assessor name"]} else {} end)
    + (if (.["SCN related vulnerability"] // "" | present)
       then {"relatedVulnerability": .["SCN related vulnerability"]} else {} end)
    + (if (.["SCN business or security impact analysis"] // "" | present)
       then {"impactAnalysis": .["SCN business or security impact analysis"]} else {} end)
    + (
        (list_from(.["SCN impacted KSIs or Rev5 controls (comma-separated)"])) as $controls
        | if ($controls | length) > 0 then {"impactedControls": $controls} else {} end
      )
    + (
        if (.["SCN plan and timeline summary"] // "" | present) then
          {
            "planAndTimeline": (
              {"summary": .["SCN plan and timeline summary"]}
              + (if (.["SCN planned start"] // "" | present)
                 then {"plannedStart": .["SCN planned start"]} else {} end)
              + (if (.["SCN planned completion"] // "" | present)
                 then {"plannedCompletion": .["SCN planned completion"]} else {} end)
              + (
                  (milestones_from(.["SCN milestones (semicolon-separated: description | YYYY-MM-DD; description | YYYY-MM-DD)"])) as $m
                  | if ($m | length) > 0 then {"milestones": $m} else {} end
                )
            )
          }
        else {} end
      )
  )
