"""Auto-detects and parses the *message* portion of a syslog line -- the
part rain.modules.tickets.syslog_parser leaves as an opaque string after
stripping the RFC 3164/5424 envelope (PRI, timestamp, host, tag). Not
every device speaks plain syslog text there: CEF (ArcSight Common Event
Format, what most SIEMs/EDRs -- Wazuh included -- can emit), JSON
(Wazuh's own native alert shape, or just about anything else that logs
structured events), and loose "key=value" pairs (Splunk's own generic
extraction target, no fixed schema) are all common on the wire, still
carried inside a standard syslog envelope.

Nothing here changes tenant routing or the envelope fields (host,
program, facility, severity stay exactly what syslog_parser already
extracted from PRI/header) -- this only enriches what would otherwise be
a raw, hard-to-read blob sitting in SyslogEvent.message. `raw` already
preserves the untouched original line regardless of what's found here.
"""
from __future__ import annotations

import json
import re

# Unescaped "|" only -- CEF's own escaping rule for its 7 pipe-delimited
# header fields is "\|" for a literal pipe, "\\" for a literal backslash.
_CEF_HEADER_SPLIT_RE = re.compile(r"(?<!\\)\|")

# A CEF extension key: starts a run of alnum/dot characters immediately
# after start-of-string or whitespace, followed by "=". Extension values
# can contain spaces (unlike a bare space-delimited key=value pair), so
# a value is "everything up to the next recognized key=", not "up to the
# next space" -- this regex only finds the key boundaries; the value
# text between them is sliced out separately (_parse_cef_extension).
_CEF_EXT_KEY_RE = re.compile(r"(?:^|\s)([A-Za-z][\w.]*)=")

# Splunk-style loose key=value / key="quoted value" pairs -- no formal
# grammar, this is the same generic pattern Splunk's own kv extraction
# looks for. Deliberately permissive on the key charset (Splunk field
# names commonly include dots/underscores).
_KV_RE = re.compile(r'([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|\S+)')

# A message is only treated as key=value pairs if at least this many are
# found -- one stray "=" in an otherwise plain sentence ("error code=5")
# shouldn't flip the whole event into "kv" format for one field.
_KV_MIN_PAIRS = 2


def _unescape_cef_header(value: str) -> str:
    return value.replace("\\|", "|").replace("\\\\", "\\")


def _unescape_cef_extension_value(value: str) -> str:
    return value.replace("\\=", "=").replace("\\n", "\n").replace("\\\\", "\\")


def parse_cef(text: str) -> dict[str, str] | None:
    """CEF:Version|Vendor|Product|Version|SignatureID|Name|Severity|Extension
    -- the first 7 fields are positional and pipe-delimited; Extension is
    space-separated key=value pairs whose values may themselves contain
    spaces. Returns None if `text` isn't CEF-shaped at all (not just a
    malformed one -- a real device occasionally truncates a line, and a
    partial/odd result is still more useful than discarding it)."""
    if not text.startswith("CEF:"):
        return None
    parts = _CEF_HEADER_SPLIT_RE.split(text[4:], maxsplit=7)
    if len(parts) < 7:
        return None
    version, vendor, product, device_version, signature_id, name, severity = (
        _unescape_cef_header(p) for p in parts[:7]
    )
    fields = {
        "cef_version": version,
        "device_vendor": vendor,
        "device_product": product,
        "device_version": device_version,
        "signature_id": signature_id,
        "name": name,
        "severity": severity,
    }
    if len(parts) > 7:
        fields.update(_parse_cef_extension(parts[7]))
    return fields


def _parse_cef_extension(extension: str) -> dict[str, str]:
    matches = list(_CEF_EXT_KEY_RE.finditer(extension))
    result: dict[str, str] = {}
    for i, match in enumerate(matches):
        value_start = match.end()
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(extension)
        result[match.group(1)] = _unescape_cef_extension_value(extension[value_start:value_end].strip())
    return result


def parse_json_object(text: str) -> dict | None:
    """None for anything that isn't a JSON *object* -- a bare JSON array
    or scalar wouldn't have named fields to work with the way the rest
    of this module (and callers matching against them) expects."""
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_kv(text: str) -> dict[str, str] | None:
    matches = _KV_RE.findall(text)
    if len(matches) < _KV_MIN_PAIRS:
        return None
    result: dict[str, str] = {}
    for key, value in matches:
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1].replace('\\"', '"')
        result[key] = value
    return result


def detect_and_parse(text: str) -> tuple[str, dict | None]:
    """Tries each format in order of how unambiguous its own marker is --
    CEF's "CEF:" prefix first, then a JSON object (brace-wrapped and
    actually parses), then the loose key=value heuristic last, since
    it's the easiest to false-positive on (e.g. a CEF extension's own
    body would also match it, if checked first). Falls back to
    ("plain", None), meaning: leave message exactly as syslog_parser
    already produced it."""
    text = text.strip()
    if not text:
        return "plain", None
    if text.startswith("CEF:"):
        fields = parse_cef(text)
        if fields:
            return "cef", fields
    if text.startswith("{"):
        fields = parse_json_object(text)
        if fields:
            return "json", fields
    fields = parse_kv(text)
    if fields:
        return "kv", fields
    return "plain", None


def _dig(data: dict, *path: str) -> str | None:
    value: object = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value.strip() if isinstance(value, str) and value.strip() else None


def summarize(event_format: str, fields: dict, fallback: str) -> str:
    """A human-readable one-liner for whatever got parsed, used as
    SyslogEvent.message in place of the raw CEF/JSON/kv text -- so the
    Events feed, a promoted ticket's title, and any Event Promotion
    Policy matching against `message` see something legible instead of a
    wall of key=value pairs or a JSON blob. Falls back to the original
    (pre-parse) message if nothing recognizable is found -- never
    returns an empty string."""
    if event_format == "cef":
        return fields.get("name") or fallback
    if event_format == "json":
        # Checked in order: a plain "message"/"msg" field first (most
        # log shippers), then Wazuh's own nested alert shape
        # (rule.description, with full_log as its own raw-text fallback).
        for path in (("message",), ("msg",), ("rule", "description"), ("full_log",)):
            value = _dig(fields, *path)
            if value:
                return value
        return fallback
    if event_format == "kv":
        for key in ("msg", "message", "description"):
            value = fields.get(key)
            if value and value.strip():
                return value.strip()
        return fallback
    return fallback
