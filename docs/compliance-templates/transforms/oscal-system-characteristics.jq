# oscal-system-characteristics.jq
#
# Step 1 of the OSCAL System Security Plan Export Recipe (see
# docs/oscal-ssp-showcase.md). Turns a JSON export of the FedRAMP
# Certification Package asset type (fedramp-certification-package.rain,
# "most tenants only ever need one" row) into an OSCAL
# system-characteristics object -- system name/description, the FIPS
# 199 security-impact-level triad, an overall security-sensitivity-
# level (the FIPS 199 "high water mark" of that triad), status, and
# the authorization boundary description.
#
# Expects the export's column headers to match fedramp-certification-
# package.rain's own custom field labels exactly, plus the asset
# exporter's own built-in "Name" column -- same convention
# fedramp-package-overview-export.jq already established for this same
# asset type. Takes the first row and ignores any others, same
# reasoning as that transform.
#
# Used standalone (Assets export's own JSON transform step) or, more
# usefully, as an Export Recipe step's own filter -- its output is
# exactly the shape oscal-ssp-assembly.jq expects under its
# "characteristics" step.

def present: . != null and (. | tostring | length) > 0;

# FIPS 199's own rule: the system's overall categorization is the
# highest of its three objective-level impacts, not an independent
# judgment call -- "moderate" confidentiality + "high" availability
# categorizes the whole system "high," for instance.
def impact_rank: {"Low": 1, "Moderate": 2, "High": 3};

.[0] as $row
| ($row["FIPS 199 confidentiality impact"] // "") as $confidentiality
| ($row["FIPS 199 integrity impact"] // "") as $integrity
| ($row["FIPS 199 availability impact"] // "") as $availability
| (
    [$confidentiality, $integrity, $availability]
    | map(select(present))
    | map(impact_rank[.])
    | if length > 0 then max else null end
  ) as $highest_rank
| ((impact_rank | with_entries(select(.value == $highest_rank)) | keys | first) // "") as $sensitivity_level
| {}
  + (if ($row["Name"] // "" | present) then {"system-name": $row["Name"]} else {} end)
  + (if ($row["Service description"] // "" | present) then {"description": $row["Service description"]} else {} end)
  + (if ($sensitivity_level | present) then {"security-sensitivity-level": ($sensitivity_level | ascii_downcase)} else {} end)
  + (
      {}
      + (if ($confidentiality | present) then {"security-objective-confidentiality": ($confidentiality | ascii_downcase)} else {} end)
      + (if ($integrity | present) then {"security-objective-integrity": ($integrity | ascii_downcase)} else {} end)
      + (if ($availability | present) then {"security-objective-availability": ($availability | ascii_downcase)} else {} end)
      | if length > 0 then {"security-impact-level": .} else {} end
    )
  + {"status": {"state": "operational"}}
  + (if ($row["Authorization boundary description"] // "" | present)
     then {"authorization-boundary": {"description": $row["Authorization boundary description"]}} else {} end)
  + (if ($row["FedRAMP package ID"] // "" | present)
     then {"system-ids": [{"identifier-type": "https://fedramp.gov", "id": $row["FedRAMP package ID"]}]} else {} end)
