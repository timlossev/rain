"""Hand-written RFC 3164 / RFC 5424 syslog line parser -- deliberately no
third-party syslog library, to keep the worker image's dependency surface
small. Falls back gracefully: an unparsed line still becomes an event with
the raw text as its message, just without host/program/severity."""
from __future__ import annotations

import re
from dataclasses import dataclass

_RFC5424_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>(?P<version>\d+)\s+(?P<timestamp>\S+)\s+(?P<host>\S+)\s+"
    r"(?P<app>\S+)\s+(?P<procid>\S+)\s+(?P<msgid>\S+)\s+"
    r"(?P<sd>-|(?:\[[^\]]*\])+)\s?(?P<msg>.*)$"
)

_RFC3164_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>(?P<timestamp>[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+(?P<tag>[^:\[\s]+)(?:\[(?P<pid>\d+)\])?:\s*(?P<msg>.*)$"
)

_PRI_ONLY_RE = re.compile(r"^<(?P<pri>\d{1,3})>(?P<rest>.*)$")

SEVERITY_LABELS = {
    0: "emerg",
    1: "alert",
    2: "crit",
    3: "err",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug",
}


@dataclass
class ParsedEvent:
    host: str | None
    program: str | None
    facility: int | None
    severity: int | None
    message: str
    raw: str


def severity_label(severity: int | None) -> str:
    return SEVERITY_LABELS.get(severity, "unknown") if severity is not None else "unknown"


def _clean(value: str | None) -> str | None:
    return None if value in (None, "-") else value


def parse_line(line: str) -> ParsedEvent:
    raw = line
    text = line.strip("\r\n")

    match = _RFC5424_RE.match(text)
    if match:
        pri = int(match.group("pri"))
        return ParsedEvent(
            host=_clean(match.group("host")),
            program=_clean(match.group("app")),
            facility=pri // 8,
            severity=pri % 8,
            message=match.group("msg").strip() or text,
            raw=raw,
        )

    match = _RFC3164_RE.match(text)
    if match:
        pri = int(match.group("pri"))
        return ParsedEvent(
            host=_clean(match.group("host")),
            program=_clean(match.group("tag")),
            facility=pri // 8,
            severity=pri % 8,
            message=match.group("msg").strip() or text,
            raw=raw,
        )

    match = _PRI_ONLY_RE.match(text)
    if match:
        pri = int(match.group("pri"))
        return ParsedEvent(
            host=None,
            program=None,
            facility=pri // 8,
            severity=pri % 8,
            message=match.group("rest").strip(),
            raw=raw,
        )

    return ParsedEvent(host=None, program=None, facility=None, severity=None, message=text, raw=raw)
