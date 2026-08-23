from __future__ import annotations

# A ticket-scoped rain.db.tenant_models.CustomField never honors
# is_required, unlike an asset-scoped one -- a ticket can be created by
# several automated paths that don't know about custom fields at all
# (an Event Promotion Policy promoting a syslog event, the public
# portal's Service Catalog submissions, CSV/JSON import), and a required
# field would silently break those instead of just being asked for on
# the manual "New ticket" form the way it can be for an asset (always
# created by hand, through one form).

TICKET_TYPES = ["incident", "vulnerability", "change"]
TICKET_TYPE_PREFIX = {"incident": "INC", "vulnerability": "VULN", "change": "CHG"}
SEVERITIES = ["low", "medium", "high", "critical"]
MATCH_FIELDS = ["message", "host", "program"]
CHANNEL_TYPES = ["email", "slack", "webhook"]
