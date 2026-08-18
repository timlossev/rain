from __future__ import annotations

from rain.modules.tickets.event_formats import detect_and_parse, parse_cef, parse_json_object, parse_kv, summarize


def test_parse_cef_header_and_extension():
    line = "CEF:0|Wazuh|Wazuh|4.3.0|5501|User login failed|5|src=192.168.1.1 suser=admin msg=Login denied for user"
    fields = parse_cef(line)
    assert fields["device_vendor"] == "Wazuh"
    assert fields["device_product"] == "Wazuh"
    assert fields["signature_id"] == "5501"
    assert fields["name"] == "User login failed"
    assert fields["severity"] == "5"
    assert fields["src"] == "192.168.1.1"
    assert fields["suser"] == "admin"
    # Extension values can contain spaces -- terminated by the next
    # recognized key=, not by whitespace.
    assert fields["msg"] == "Login denied for user"


def test_parse_cef_escaped_pipe_in_header():
    line = r"CEF:0|Acme\|Corp|Product|1.0|100|Name|3|src=1.2.3.4"
    fields = parse_cef(line)
    assert fields["device_vendor"] == "Acme|Corp"


def test_parse_cef_not_cef():
    assert parse_cef("not a cef line") is None
    assert parse_cef("CEF:only|six|fields|here|not|seven") is None


def test_parse_json_object():
    data = parse_json_object('{"rule": {"level": 7, "description": "Login failed"}, "agent": {"name": "host1"}}')
    assert data["rule"]["description"] == "Login failed"
    assert data["agent"]["name"] == "host1"


def test_parse_json_rejects_non_object():
    assert parse_json_object("[1, 2, 3]") is None
    assert parse_json_object("not json at all") is None
    assert parse_json_object("{not valid json}") is None


def test_parse_kv_basic():
    fields = parse_kv('level=7 rule=5501 description="User login failed" srcip=192.168.1.1 user=admin')
    assert fields["level"] == "7"
    assert fields["description"] == "User login failed"
    assert fields["srcip"] == "192.168.1.1"


def test_parse_kv_requires_at_least_two_pairs():
    # A single stray "=" in an otherwise plain sentence shouldn't flip
    # the whole line into "kv" format.
    assert parse_kv("error code=5 happened") is None


def test_detect_and_parse_cef():
    fmt, fields = detect_and_parse("CEF:0|Wazuh|Wazuh|4.3.0|5501|User login failed|5|src=1.2.3.4")
    assert fmt == "cef"
    assert fields["name"] == "User login failed"


def test_detect_and_parse_json():
    fmt, fields = detect_and_parse('{"message": "disk full", "host": "db1"}')
    assert fmt == "json"
    assert fields["message"] == "disk full"


def test_detect_and_parse_kv():
    fmt, fields = detect_and_parse("level=7 rule=5501 description=test")
    assert fmt == "kv"
    assert fields["rule"] == "5501"


def test_detect_and_parse_plain_fallback():
    fmt, fields = detect_and_parse("just a normal log line with no structure")
    assert fmt == "plain"
    assert fields is None


def test_summarize_cef_uses_name():
    assert summarize("cef", {"name": "User login failed"}, "fallback") == "User login failed"


def test_summarize_json_prefers_message_then_nested_rule_description():
    assert summarize("json", {"message": "disk full"}, "fallback") == "disk full"
    assert summarize("json", {"rule": {"description": "Login failed"}}, "fallback") == "Login failed"
    assert summarize("json", {"full_log": "raw line text"}, "fallback") == "raw line text"
    assert summarize("json", {"unrelated": "field"}, "fallback") == "fallback"


def test_summarize_kv_prefers_msg_then_message_then_description():
    assert summarize("kv", {"msg": "hello"}, "fallback") == "hello"
    assert summarize("kv", {"description": "world"}, "fallback") == "world"
    assert summarize("kv", {"other": "x"}, "fallback") == "fallback"


def test_summarize_plain_always_falls_back():
    assert summarize("plain", {}, "original message") == "original message"
