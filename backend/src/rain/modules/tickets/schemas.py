from __future__ import annotations

TICKET_TYPES = ["incident", "vulnerability", "change"]
TICKET_TYPE_PREFIX = {"incident": "INC", "vulnerability": "VULN", "change": "CHG"}
SEVERITIES = ["low", "medium", "high", "critical"]
MATCH_FIELDS = ["message", "host", "program"]
CHANNEL_TYPES = ["email", "slack", "webhook"]
