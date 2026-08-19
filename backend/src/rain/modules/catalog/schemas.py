from __future__ import annotations

# incident | vulnerability | change -- kept as a separate list rather than
# importing rain.modules.tickets.schemas.TICKET_TYPES directly so this
# module's public surface doesn't implicitly change if that list ever
# grows for a reason that has nothing to do with the catalog (unlikely,
# but cheap to keep decoupled -- there's exactly one other place, MATCH_
# FIELDS, that already gets imported directly instead, and that one *is*
# meant to move in lockstep).
from rain.modules.tickets.schemas import TICKET_TYPES  # noqa: F401

#: How a submission's answers are serialized into the produced ticket's
#: description -- see rain.modules.catalog.service.render_payload.
PAYLOAD_FORMATS = ["json", "kv"]

#: How a field's value/options are sourced from a Document instead of (or
#: as a fallback for) free-form entry -- see rain.modules.catalog.service.
#: resolve_field_source. Empty string (not a member of this list) means
#: "not document-sourced" -- the plain static field.
SOURCE_MODES = ["content", "regex", "jsonpath"]

#: A catalog item can have at most this many questions -- enforced at the
#: app layer (rain.modules.admin's catalog routes), same "form pre-renders
#: N rows, a blank one is simply skipped on submit" trade-off as
#: admin.router._MAX_APPROVAL_STEPS.
MAX_CATALOG_FIELDS = 10
