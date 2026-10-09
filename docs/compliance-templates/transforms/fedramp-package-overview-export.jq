# fedramp-package-overview-export.jq
#
# Turns an Assets JSON export (asset type "FedRAMP Certification
# Package", with fedramp-certification-package.rain's own fields
# selected) into the core of a FedRAMP Certification Package Overview,
# valid against fedramp-certification-package-overview-schema-2026-06-24.
# json once contactInformation is filled in (see below) -- "most tenants
# only ever need one" row per that bundle's own docstring, so this takes
# the first row in the export and ignores any others.
#
# contactInformation is a REQUIRED array the schema also requires to
# contain at least one Security and one Sales contact -- that data lives
# on a *different* asset type (FedRAMP Package Contact), which an Assets
# export can't join in from here. This transformer emits an empty
# contactInformation array (structurally valid, substantively
# incomplete) and expects you to splice in
# fedramp-package-contacts-export.jq's own output by hand. Same story
# for additionalRepositories/trustCenter/secureConfigurationGuidance
# (optional, not required, but still a separate asset type) --
# fedramp-package-repositories-export.jq produces that fragment.
#
# Expects the export's column headers to match
# fedramp-certification-package.rain's own custom field labels exactly
# (the default when you don't rename them on the export screen), plus
# the asset exporter's own built-in "Name" column (-> serviceName).

def present: . != null and (. | tostring | length) > 0;

def list_from(text):
  if (text | present) then
    text | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(present))
  else [] end;

.[0] as $row
| (
    {}
    + (if ($row["Provider name"] // "" | present) then {"providerName": $row["Provider name"]} else {} end)
    + (if ($row["Name"] // "" | present) then {"serviceName": $row["Name"]} else {} end)
    + (if ($row["Service acronym"] // "" | present) then {"serviceAcronym": $row["Service acronym"]} else {} end)
    + (if ($row["Service description"] // "" | present) then {"serviceDescription": $row["Service description"]} else {} end)
    + (if ($row["Certification type"] // "" | present) then {"certificationType": $row["Certification type"]} else {} end)
    + (if ($row["FedRAMP package ID"] // "" | present) then {"fedRampPackageId": $row["FedRAMP package ID"]} else {} end)
    + (if ($row["UEI number (SAM.gov)"] // "" | present) then {"ueiNumber": $row["UEI number (SAM.gov)"]} else {} end)
    + (if ($row["Website"] // "" | present) then {"website": $row["Website"]} else {} end)
    + (if ($row["Logo URL (png/jpeg/gif/svg/webp/ico/bmp/tiff)"] // "" | present)
       then {"logo": $row["Logo URL (png/jpeg/gif/svg/webp/ico/bmp/tiff)"]} else {} end)
  ) as $serviceIdentification
| (
    (list_from($row["Service type (comma-separated -- SaaS, PaaS, IaaS)"])) as $serviceType
    | (list_from($row["Business category (comma-separated, up to 10)"])) as $businessCategory
    | {}
      + (if ($serviceType | length) > 0 then {"serviceType": $serviceType} else {} end)
      + (if ($row["Deployment model"] // "" | present) then {"deploymentModel": $row["Deployment model"]} else {} end)
      + (if ($businessCategory | length) > 0 then {"businessCategory": $businessCategory} else {} end)
      + (if ($row["Next Ongoing Certification Report date"] // "" | present)
         then {"nextOngoingCertificationReportDate": $row["Next Ongoing Certification Report date"]} else {} end)
  ) as $serviceProperties
| (
    {}
    + (if ($row["Assessor (3PAO) name"] // "" | present) then {"name": $row["Assessor (3PAO) name"]} else {} end)
    + (if ($row["Assessor ID (6 digits)"] // "" | present) then {"assessorID": $row["Assessor ID (6 digits)"]} else {} end)
  ) as $assessor
| {
    "serviceIdentification": $serviceIdentification,
    "serviceProperties": $serviceProperties,
    "contactInformation": []
  }
  + (if ($assessor | length) > 0 then {"assessor": $assessor} else {} end)
