# fedramp-ksi-sdr-assembly.jq
#
# The "assembly filter" of the FedRAMP Security Decision Record Export
# Recipe (see docs/compliance-templates/README.md) -- NOT something
# you run from an Assets export screen directly. Pick this as an
# Export Recipe's own "Assembly filter (optional)", run once over the
# {label: value} object collected from that recipe's own steps:
#
#   Step 1, label "controls": profile over the Security Control asset
#     type, filter fedramp-security-decision-record-export.jq
#     (unchanged -- its own output is already a complete Security
#     Decision Record document, just with keySecurityIndicators
#     permanently empty; this assembly filter only reaches into it for
#     securityControls/certificationPackageOverviewUri/metadata).
#   Step 2, label "ksis": profile over the Key Security Indicator
#     asset type, filter fedramp-ksi-export.jq.
#
# Produces one real fedramp-security-decision-record-schema-2026-06-
# 24.json document with keySecurityIndicators actually populated.
# fedRampRequirements/portsAndProtocols stay empty placeholders, same
# reasoning fedramp-security-decision-record-export.jq's own docstring
# already gives: no asset type in this repo models either one yet.

def present: . != null and (. | tostring | length) > 0;

(.controls.securityControls // []) as $securityControls
| (.ksis // []) as $keySecurityIndicators
| (.controls.metadata // {"lastUpdated": (now | todate)}) as $metadata
| {
    "securityControls": $securityControls,
    "fedRampRequirements": [],
    "keySecurityIndicators": $keySecurityIndicators,
    "portsAndProtocols": []
  }
  + (if (.controls.certificationPackageOverviewUri // "" | present)
     then {"certificationPackageOverviewUri": .controls.certificationPackageOverviewUri} else {} end)
  + {"metadata": $metadata}
