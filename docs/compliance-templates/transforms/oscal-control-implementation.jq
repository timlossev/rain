# oscal-control-implementation.jq
#
# Turns a JSON export of Security Control assets (security-control-
# register.rain) into an OSCAL control-implementation fragment --
# implemented-requirements[], one per control-id, each carrying its
# narrative, implementation status, responsible role, and (for a
# control tracked at part-level) one statement per part. This is a
# fragment, not a complete system-security-plan: OSCAL's own metadata,
# system-characteristics, and system-implementation sections describe
# things a per-control asset row has no way to know (system name,
# authorization boundary, component inventory, ...) and are expected
# to be authored separately, with this fragment's own
# "implemented-requirements" array spliced into that document's own
# "control-implementation" object.
#
# Expects the export's column headers to match this template's custom
# field labels exactly (the default when you don't rename them on the
# export screen): CI Number, Control ID, Statement ID, Implementation
# Status, Narrative, Responsible Role, Parameters, Remarks.
#
# Two ways to use one control's rows:
#   - One row, Statement ID left blank: the narrative goes directly on
#     that control's own "description" -- the common case, for a
#     control your organization tracks as a single unit.
#   - Multiple rows sharing the same Control ID, each with its own
#     Statement ID (e.g. "ac-3_smt.a", "ac-3_smt.b"): grouped into one
#     implemented-requirement with a "statements" array, one entry per
#     part -- for a control your organization tracks (and assigns
#     status/an owner to) at the lettered-part level instead.
#
# uuid/statement uuid: OSCAL requires one, globally unique, per object.
# This derives a stable, schema-shaped one from each row's own RAIN CI
# Number (already unique per tenant) rather than generating a random
# one -- deterministic on purpose, so re-exporting the same control
# later produces the same uuid instead of a new one every time. Not
# RFC 4122 random (jq has no crypto/hash builtin to draw on), but a
# small djb2-style string hash run five times with different salts
# spreads the CI Number across every group instead of leaving most of
# it a fixed "00000000-0000-...-<padded number>" -- version/variant
# nibbles are still forced (4.../8-b...) so it's shaped like a real v4
# UUID. num_uuid's own salt argument keeps an implemented-requirement
# and the first row in its own "statements" array -- which, for a
# multi-row control, is the very CI Number this same $first came from
# -- from colliding just because they're derived from the same row.

def dhash(seed):
  explode | reduce .[] as $c (seed; (. * 131 + $c) % 2147483648);

def hex(n; width):
  reduce range(width) as $i ({n: n, s: ""};
    {n: (.n / 16 | floor), s: ("0123456789abcdef"[(.n % 16 | floor):(.n % 16 | floor) + 1] + .s)}
  ) | .s;

def num_uuid(salt):
  (. // "CI-0") as $key
  | ((salt + "1:" + $key) | dhash(5381)) as $h1
  | ((salt + "2:" + $key) | dhash(5381)) as $h2
  | ((salt + "3:" + $key) | dhash(5381)) as $h3
  | ((salt + "4:" + $key) | dhash(5381)) as $h4
  | ((salt + "5:" + $key) | dhash(5381)) as $h5
  | (hex($h1; 8)) as $g1
  | (hex($h2; 4)) as $g2
  | ("4" + hex($h3; 3)) as $g3
  | (("89ab"[($h4 % 4):($h4 % 4) + 1]) + hex($h4; 3)) as $g4
  | (hex($h5; 8) + hex($h1; 4)) as $g5
  | "\($g1)-\($g2)-\($g3)-\($g4)-\($g5)";

def kebab: ascii_downcase | gsub(" +"; "-");
def present: . != null and . != "";

group_by(.["Control ID"])
| map(
    (.[0]) as $first
    | {
        "uuid": (($first["CI Number"] // "CI-0") | num_uuid("9")),
        "control-id": (($first["Control ID"] // "") | ascii_downcase),
        "props": (
          [ if ($first["Implementation Status"] | present)
            then {"name": "implementation-status", "value": ($first["Implementation Status"] | kebab)}
            else empty end
          , if ($first["Parameters"] | present)
            then {"name": "parameters", "value": $first["Parameters"]}
            else empty end
          ]
        )
      }
      + (
        if (length == 1) and (((.[0]["Statement ID"]) // "") == "")
        then { "description": ((.[0]["Narrative"]) // "") }
        else {
          "statements": map(
            {
              "statement-id": ((.["Statement ID"]) // ($first["Control ID"] + "_smt")),
              "uuid": ((.["CI Number"] // "CI-0") | num_uuid("0")),
              "description": ((.["Narrative"]) // "")
            }
            + (if (.["Remarks"] | present) then {"remarks": .["Remarks"]} else {} end)
          )
        }
        end
      )
      + (if ($first["Responsible Role"] | present)
         then {"responsible-roles": [{"role-id": ($first["Responsible Role"] | kebab)}]}
         else {} end)
      + (if ($first["Remarks"] | present) then {"remarks": $first["Remarks"]} else {} end)
  )
| sort_by(.["control-id"])
| {
    "control-implementation": {
      "description": "Control implementation statements exported from RAIN Security Control assets.",
      "implemented-requirements": .
    }
  }
