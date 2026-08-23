"""Tests that need no database: field coercion, password hashing, the
CSV/JSON export/import round trip, and the field-pack type-guessing
heuristic."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from rain.core.field_pack import sniff_columns, slugify_key
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


def test_field_pack_slugify_key():
    assert slugify_key("Warranty Expiry") == "warranty_expiry"
    assert slugify_key("2024 Budget") == "f_2024_budget"
    assert slugify_key("  ") == "field"


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_field_pack_guesses_types_from_samples():
    raw = _xlsx_bytes(
        [
            ["CAB Reference", "Approved", "Budget", "Contact Email", "Environment"],
            ["CAB-1001", "yes", "1200.50", "a@example.com", "prod"],
            ["CAB-1002", "no", "300", "b@example.com", "staging"],
            ["CAB-1003", "yes", "42", "c@example.com", "prod"],
            ["CAB-1004", "no", "17", "d@example.com", "dev"],
        ]
    )
    guesses = {g.header: g for g in sniff_columns(raw, "xlsx")}

    assert guesses["CAB Reference"].field_type == "text"
    assert guesses["CAB Reference"].field_key == "cab_reference"
    assert guesses["Approved"].field_type == "boolean"
    assert guesses["Budget"].field_type == "number"
    assert guesses["Contact Email"].field_type == "email"
    assert guesses["Environment"].field_type == "select"
    assert sorted(guesses["Environment"].select_options) == ["dev", "prod", "staging"]


def test_field_pack_header_only_file_defaults_to_text():
    raw = _xlsx_bytes([["Notes"]])
    guesses = sniff_columns(raw, "xlsx")
    assert len(guesses) == 1
    assert guesses[0].field_type == "text"
    assert guesses[0].samples == []


def test_field_pack_csv_and_blank_headers_skipped():
    raw = b"Name,,Status\nweb-01,x,active\n"
    guesses = sniff_columns(raw, "csv")
    assert [g.header for g in guesses] == ["Name", "Status"]
