# fedramp-security-decision-record-export.jq
#
# Turns an Assets JSON export (asset type "Security Control", with
# security-control-register.rain's own fields selected -- the same
# register oscal-control-implementation.jq already exports as OSCAL)
# into the securityControls[] portion of a FedRAMP Security Decision
# Record, part of fedramp-security-decision-record-schema-2026-06-24.
# json.
#
# This is a FRAGMENT, not a complete Security Decision Record -- that
# schema's other three sections (fedRampRequirements, which needs
# separate implementation/validation/assessment narrative statements per
# FRR, not a single status+description the way a control does;
# keySecurityIndicators, same shape plus structured test/evidence
# records; portsAndProtocols) describe things no asset type in this
# repo tracks yet -- RAIN's Security Control register models "one
# control, one status, one narrative," not "one requirement, three
# separate narrative arrays plus an evidence array." Those three come
# out as present-but-empty placeholders below; filling them in means
# either hand-authoring that JSON directly or building the asset
# types/fields to track them first (ask if you want that built).
#
# parameterValues (per-parameter id/value pairs within a control) is
# also left out -- the register's own "Parameters" field is free text
# with no established id=value structure to parse out of it reliably,
# so this doesn't guess at one.
#
# controlImplementationStatus is passed through as-is from
# "Implementation Status," not remapped -- this schema's own enum
# (Implemented/Not Implemented/Partially Implemented) is narrower than
# the register's own (which also allows Planned/Alternative
# Implementation/Not Applicable, matching FedRAMP's OSCAL baseline
# vocabulary instead). A row using one of those three extra values will
# fail schema validation until you either change it on the control or
# treat this export as needing a manual pass first -- not silently
# guessed at here.
#
# EDIT THIS BEFORE USE: the three constants below are per-CSP/per-export
# metadata, not per-row data.
#
# Expects the export's column headers to match
# security-control-register.rain's own custom field labels exactly (the
# default when you don't rename them on the export screen).

def certification_package_overview_uri: "";
def metadata_version: "";       # e.g. "1.0"
def metadata_update_source: ""; # e.g. "RAIN export"

def present: . != null and (. | tostring | length) > 0;

[
  .[]
  | {}
    + (if (.["Control ID"] // "" | present) then {"controlId": .["Control ID"]} else {} end)
    + (if (.["Implementation Status"] // "" | present)
       then {"controlImplementationStatus": .["Implementation Status"]} else {} end)
    + (if (.["Narrative"] // "" | present) then {"controlImplementationDescription": .["Narrative"]} else {} end)
] as $securityControls
| (
    {}
    + (if (metadata_version | present) then {"version": metadata_version} else {} end)
    + (if (metadata_update_source | present) then {"updateSource": metadata_update_source} else {} end)
    + {"lastUpdated": (now | todate)}
  ) as $metadata
| {
    "securityControls": $securityControls,
    "fedRampRequirements": [],
    "keySecurityIndicators": [],
    "portsAndProtocols": []
  }
  + (if (certification_package_overview_uri | present)
     then {"certificationPackageOverviewUri": certification_package_overview_uri} else {} end)
  + {"metadata": $metadata}
