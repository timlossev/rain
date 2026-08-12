from __future__ import annotations

TICKET_TYPES = ["incident", "vulnerability"]
TICKET_TYPE_PREFIX = {"incident": "INC", "vulnerability": "VULN"}
TICKET_STATUSES = ["open", "in_progress", "resolved", "closed"]
SEVERITIES = ["low", "medium", "high", "critical"]
MATCH_FIELDS = ["message", "host", "program"]
CHANNEL_TYPES = ["email", "slack"]
