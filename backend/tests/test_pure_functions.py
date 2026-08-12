"""Tests that need no database: field coercion, password hashing, and the
CSV/JSON export/import round trip."""
from __future__ import annotations

from rain.core.security import hash_password, hash_session_token, new_session_token, verify_password
from rain.modules.assets import exporter, importer
from rain.modules.assets.schemas import coerce_field_value


def test_coerce_field_value_number():
    assert coerce_field_value("number", "42") == 42
    assert coerce_field_value("number", "3.14") == 3.14
    assert coerce_field_value("number", "") is None


def test_coerce_field_value_boolean():
    assert coerce_field_value("boolean", "on") is True
    assert coerce_field_value("boolean", "false") is False
    assert coerce_field_value("boolean", None) is None


def test_coerce_field_value_text_passthrough():
    assert coerce_field_value("text", "hello") == "hello"


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_session_token_hash_is_deterministic_and_not_reversible():
    token = new_session_token()
    assert hash_session_token(token) == hash_session_token(token)
    assert hash_session_token(token) != token


def test_csv_export_import_roundtrip():
    rows = [{"Name": "web-01", "Status": "active"}, {"Name": "web-02", "Status": "retired"}]
    csv_text = exporter.render_csv(rows, ["Name", "Status"])
    parsed = importer.parse_rows(csv_text.encode("utf-8"), "csv")
    assert parsed == rows


def test_json_export_import_roundtrip():
    rows = [{"Name": "web-01"}]
    json_text = exporter.render_json(rows)
    parsed = importer.parse_rows(json_text.encode("utf-8"), "json")
    assert parsed == rows


def test_import_sniff_headers_csv():
    raw = b"Name,External ID\nweb-01,SN1\n"
    assert importer.sniff_headers(raw, "csv") == ["Name", "External ID"]


def test_import_sniff_headers_json():
    raw = b'[{"Name": "web-01", "External ID": "SN1"}]'
    assert importer.sniff_headers(raw, "json") == ["Name", "External ID"]
