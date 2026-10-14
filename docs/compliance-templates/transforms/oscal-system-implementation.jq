# oscal-system-implementation.jq
#
# Step 2 of the OSCAL System Security Plan Export Recipe (see
# docs/oscal-ssp-showcase.md). Turns a JSON export of the Software
# Component asset type (software-inventory-register.rain) into OSCAL's
# system-implementation.components[] array -- one component per row.
#
# OSCAL's own component "type" enum (software/hardware/service/...) is
# coarser than this register's own Component type field (Application,
# Library / dependency, Container image, Operating system package,
# Firmware, Other) -- SBOM-level granularity like "this is a container
# image, not a bare library" isn't something plain OSCAL component
# records carry at all (that distinction lives in a CycloneDX/SPDX SBOM
# instead, a separate artifact OSCAL can reference but doesn't replace).
# component_type below maps every non-firmware kind to "software",
# honestly collapsing that distinction rather than inventing an OSCAL
# type that doesn't exist.
#
# Expects the export's column headers to match software-inventory-
# register.rain's own custom field labels exactly, plus the asset
# exporter's own built-in "CI Number"/"Name" columns.
#
# Used as an Export Recipe step's own filter -- its output is exactly
# the shape oscal-ssp-assembly.jq expects under its "components" step.

def present: . != null and (. | tostring | length) > 0;

def dhash(seed):
  explode | reduce .[] as $c (seed; (. * 131 + $c) % 2147483648);

def hex(n; width):
  reduce range(width) as $i ({n: n, s: ""};
    {n: (.n / 16 | floor), s: ("0123456789abcdef"[(.n % 16 | floor):(.n % 16 | floor) + 1] + .s)}
  ) | .s;

# Same construction as oscal-control-implementation.jq's own num_uuid --
# deterministic from the row's own CI Number, so re-exporting later
# produces the same component uuid rather than a new one every time.
def num_uuid(salt):
  (. // "CI-0") as $key
  | ((salt + "1:" + $key) | dhash(5381)) as $h1
  | ((salt + "2:" + $key) | dhash(5381)) as $h2
  | ((salt + "3:" + $key) | dhash(5381)) as $h3
  | ((salt + "4:" + $key) | dhash(5381)) as $h4
  | ((salt + "5:" + $key) | dhash(5381)) as $h5
  | (hex($h1; 8)) as $p1
  | (hex($h2; 4)) as $p2
  | ("4" + hex($h3; 3)) as $p3
  | (hex(8 + ($h4 % 4); 1) + hex($h4; 3)) as $p4
  | (hex($h5; 12)) as $p5
  | ($p1 + "-" + $p2 + "-" + $p3 + "-" + $p4 + "-" + $p5);

def component_type:
  if . == "Firmware" then "hardware" else "software" end;

def component_status:
  if . == "Active" then "operational"
  elif . == "Under review" then "under-development"
  else "disposition" end;

[
  .[] as $row
  | (
      [$row["Vendor / source"], $row["Version"]]
      | map(select(present))
      | join(" ")
    ) as $description_bits
  | (
      []
      + (if ($row["Version"] // "" | present) then [{"name": "version", "value": $row["Version"]}] else [] end)
      + (if ($row["Vendor / source"] // "" | present) then [{"name": "vendor", "value": $row["Vendor / source"]}] else [] end)
      + (if ($row["Digest / hash"] // "" | present) then [{"name": "digest", "value": $row["Digest / hash"]}] else [] end)
      + (if ($row["License"] // "" | present) then [{"name": "license", "value": $row["License"]}] else [] end)
    ) as $props
  | {
      "uuid": (($row["CI Number"] // "CI-0") | num_uuid("component")),
      "type": (($row["Component type"] // "Other") | component_type),
      "title": ($row["Name"] // "Unnamed component"),
      "status": {"state": (($row["Status"] // "Active") | component_status)}
    }
    + (if ($description_bits | length) > 0 then {"description": $description_bits} else {} end)
    + (if ($props | length) > 0 then {"props": $props} else {} end)
    + (if ($row["Known vulnerabilities (CVE list or reference)"] // "" | present)
       then {"remarks": ("Known vulnerabilities: " + $row["Known vulnerabilities (CVE list or reference)"])} else {} end)
]
