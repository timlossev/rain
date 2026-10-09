# fedramp-package-contacts-export.jq
#
# Turns an Assets JSON export (asset type "FedRAMP Package Contact",
# with fedramp-package-contacts.rain's own fields selected) into the
# contactInformation array fragment fedramp-package-overview-export.jq
# leaves empty -- paste this output in as that key's value once both
# have run. The schema requires at least one "Security" and one "Sales"
# contactType in the array; RAIN has no way to enforce that across rows
# at export time (see fedramp-package-contacts.rain's own docstring), so
# double-check it by eye before submitting.
#
# Expects the export's column headers to match
# fedramp-package-contacts.rain's own custom field labels exactly (the
# default when you don't rename them on the export screen), plus the
# asset exporter's own built-in "Name" column (-> contactName).

def present: . != null and (. | tostring | length) > 0;

[
  .[]
  | {}
    + (if (.["Contact type"] // "" | present) then {"contactType": .["Contact type"]} else {} end)
    + (if (.["Name"] // "" | present) then {"contactName": .["Name"]} else {} end)
    + (if (.["Email"] // "" | present) then {"contactEmail": .["Email"]} else {} end)
    + (if (.["Phone (###-###-####)"] // "" | present) then {"contactPhone": .["Phone (###-###-####)"]} else {} end)
]
