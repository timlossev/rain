# fedramp-package-repositories-export.jq
#
# Turns an Assets JSON export (asset type "FedRAMP Package Repository",
# with fedramp-package-repositories.rain's own fields selected) into the
# {trustCenter, secureConfigurationGuidance, additionalRepositories}
# fragment -- paste these three keys into serviceProperties alongside
# fedramp-package-overview-export.jq's own output once both have run.
# One register covers all three of that schema's repository-shaped
# fields (see fedramp-package-repositories.rain's own docstring): a row
# whose "Repository type(s)" contains "Trust Center" (case-insensitive)
# becomes trustCenter, one containing "Secure Configuration Guidance"
# becomes secureConfigurationGuidance -- first match wins for each if
# there's more than one -- and every other row lands in
# additionalRepositories. A row matched into trustCenter or
# secureConfigurationGuidance isn't also repeated in
# additionalRepositories.
#
# Expects the export's column headers to match
# fedramp-package-repositories.rain's own custom field labels exactly
# (the default when you don't rename them on the export screen).

def present: . != null and (. | tostring | length) > 0;

def list_from(text):
  if (text | present) then
    text | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(present))
  else [] end;

def boolish: . == true or . == "true" or . == "1" or (. == "yes" or . == "Yes");

def repository:
  {}
  + (
      (list_from(.["Repository type(s) (comma-separated -- e.g. Trust Center, Secure Configuration Guidance, Assessment Reports)"])) as $types
      | if ($types | length) > 0 then {"repositoryType": $types} else {} end
    )
  + (if (.["URL"] // "" | present) then {"url": .["URL"]} else {} end)
  + (if (.["What's in it"] // "" | present) then {"repositoryDescription": .["What's in it"]} else {} end)
  + (if (.["Authentication required"] != null)
     then {"authenticationRequired": (.["Authentication required"] | boolish)} else {} end)
  + (if (.["Access request instructions (required by the schema when Authentication required is set)"] // "" | present)
     then {"accessRequestInstructions": .["Access request instructions (required by the schema when Authentication required is set)"]}
     else {} end);

def type_list:
  list_from(.["Repository type(s) (comma-separated -- e.g. Trust Center, Secure Configuration Guidance, Assessment Reports)"])
  | map(ascii_downcase);

(map(select(type_list | any(. == "trust center")))) as $trust_rows
| (map(select(type_list | any(. == "secure configuration guidance")))) as $scg_rows
| (
    map(select(
      (type_list | any(. == "trust center")) or (type_list | any(. == "secure configuration guidance"))
      | not
    ))
  ) as $other_rows
| {"additionalRepositories": [$other_rows[] | repository]}
  + (if ($trust_rows | length) > 0 then {"trustCenter": ($trust_rows[0] | repository)} else {} end)
  + (if ($scg_rows | length) > 0 then {"secureConfigurationGuidance": ($scg_rows[0] | repository)} else {} end)
