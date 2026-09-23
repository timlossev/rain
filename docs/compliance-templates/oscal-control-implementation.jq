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
# later produces the same uuid instead of a new one every time. It's
# not RFC 4122 random (the tail is just the CI Number's own digits,
# zero-padded), but nothing in the OSCAL schema requires randomness,
# only the "8-4-4-4-12 hex" shape, which this always produces. num_uuid
# takes a one-character salt so an implemented-requirement and the
# first row in its own "statements" array -- which, for a multi-row
# control, is the very CI Number this same $first came from -- don't
# collide just because they're derived from the same row.

def num_uuid(salt):
  (capture("(?<n>[0-9]+)$")?.n // "0") as $n
  | (salt + $n) as $salted
  | ($salted | if length > 12 then .[-12:] else ("000000000000"[length:] + .) end) as $tail
  | "00000000-0000-4000-8000-" + $tail;

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
