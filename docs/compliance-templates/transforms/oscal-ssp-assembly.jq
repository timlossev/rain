# oscal-ssp-assembly.jq
#
# The "assembly filter" of the OSCAL System Security Plan Export
# Recipe (see docs/oscal-ssp-showcase.md) -- NOT something you run from
# an Assets/Tickets export screen directly. This is the filter you pick
# as an Export Recipe's own "Assembly filter (optional)", run once over
# the {label: value} object collected from that recipe's own steps:
#
#   Step 1, label "characteristics": profile over the FedRAMP
#     Certification Package asset type, filter oscal-system-
#     characteristics.jq.
#   Step 2, label "components": profile over the Software Component
#     asset type, filter oscal-system-implementation.jq.
#   Step 3, label "controls": profile over the Security Control asset
#     type, filter oscal-control-implementation.jq (unchanged -- its
#     output is already shaped {"control-implementation": {...}}, so
#     this filter just lifts that object straight into place).
#
# Produces one complete OSCAL system-security-plan document --
# metadata/import-profile are boilerplate, EDIT THESE BEFORE USE.
# back-matter/system-implementation.users are schema-present but
# empty: back-matter resources (diagrams, supporting Documents) and
# system-implementation users aren't modeled by any RAIN asset type
# today, so there's nothing to populate them from yet -- same "empty
# but structurally valid" placeholder pattern fedramp-ocr-export.jq
# already uses for its own not-yet-modeled sections.

def present: . != null and (. | tostring | length) > 0;

def dhash(seed):
  explode | reduce .[] as $c (seed; (. * 131 + $c) % 2147483648);

def hex(n; width):
  reduce range(width) as $i ({n: n, s: ""};
    {n: (.n / 16 | floor), s: ("0123456789abcdef"[(.n % 16 | floor):(.n % 16 | floor) + 1] + .s)}
  ) | .s;

def num_uuid(salt):
  (. // "ssp-0") as $key
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

# EDIT THESE BEFORE USE -- this run's own document identity, not
# derivable from any asset row.
def oscal_version: "1.1.3";
def ssp_title: "System Security Plan";
def import_profile_href: "REPLACE-WITH-YOUR-PROFILE-HREF";

(.characteristics // {}) as $characteristics
| (.components // []) as $components
| ((.controls["control-implementation"]) // {"implemented-requirements": []}) as $control_implementation
| (($characteristics["system-name"] // "ssp") | num_uuid("ssp")) as $ssp_uuid
| {
    "system-security-plan": {
      "uuid": $ssp_uuid,
      "metadata": {
        "title": ssp_title,
        "last-modified": (now | todate),
        "version": "1.0.0",
        "oscal-version": oscal_version
      },
      "import-profile": {"href": import_profile_href},
      "system-characteristics": $characteristics,
      "system-implementation": {
        "users": [],
        "components": $components
      },
      "control-implementation": $control_implementation,
      "back-matter": {"resources": []}
    }
  }
