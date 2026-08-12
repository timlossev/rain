from __future__ import annotations

from rain.modules.tickets.syslog_parser import parse_line, severity_label


def test_rfc3164_line():
    event = parse_line("<34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8")
    assert event.host == "mymachine"
    assert event.program == "su"
    assert event.facility == 4
    assert event.severity == 2
    assert "su root" in event.message


def test_rfc5424_line_with_structured_data():
    line = (
        '<165>1 2003-10-11T22:14:15.003Z mymachine.example.com evntslog - ID47 '
        '[exampleSDID@32473 iut="3" eventSource="Application"] An application event log entry'
    )
    event = parse_line(line)
    assert event.host == "mymachine.example.com"
    assert event.program == "evntslog"
    assert event.facility == 20
    assert event.severity == 5
    assert event.message == "An application event log entry"


def test_pri_only_fallback():
    event = parse_line("<13>just a message with no other structure")
    assert event.facility == 1
    assert event.severity == 5
    assert event.host is None


def test_unstructured_fallback_keeps_raw_as_message():
    event = parse_line("totally unstructured line with no PRI")
    assert event.host is None
    assert event.facility is None
    assert event.message == "totally unstructured line with no PRI"


def test_severity_label():
    assert severity_label(0) == "emerg"
    assert severity_label(7) == "debug"
    assert severity_label(None) == "unknown"
    assert severity_label(99) == "unknown"
