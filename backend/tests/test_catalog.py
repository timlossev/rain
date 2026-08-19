"""Unit tests for the parts of rain.modules.catalog.service that don't
need a real database -- render_payload (pure over an item + answers) and
replace_catalog_fields (only needs a session for db.add/delete/flush,
stubbed here rather than a real one -- SQLAlchemy's relationship system
keeps item.fields in sync in memory the moment a ServiceCatalogField is
constructed with catalog_item=item, independent of any session/DB
interaction, so a no-op stand-in is enough to exercise the row-building
logic itself). Document-sourced field resolution (resolve_field_source)
and the full submit_catalog_item flow need a real Postgres (JSONB
columns, Document rows) -- see backend/tests/test_integration.py for
that coverage."""
from __future__ import annotations

from rain.db.tenant_models import ServiceCatalogItem
from rain.modules.catalog.service import ResolvedSource, render_payload, replace_catalog_fields


def _item(payload_format: str = "json") -> ServiceCatalogItem:
    return ServiceCatalogItem(name="Provision a new user", key="provision-user", payload_format=payload_format)


def test_render_payload_json():
    item = _item("json")
    text = render_payload(item, {"username": "jdoe", "domain": "IBM", "user_type": "normal"})
    assert text == '{\n  "username": "jdoe",\n  "domain": "IBM",\n  "user_type": "normal"\n}'


def test_render_payload_kv():
    item = _item("kv")
    text = render_payload(item, {"username": "jdoe", "domain": "IBM", "user_type": "normal"})
    assert text == "username=jdoe\ndomain=IBM\nuser_type=normal"


def test_render_payload_prunes_blank_answers():
    item = _item("kv")
    text = render_payload(item, {"username": "jdoe", "middle_name": None, "nickname": ""})
    assert text == "username=jdoe"


def test_render_payload_json_empty_is_empty_object():
    item = _item("json")
    assert render_payload(item, {}) == "{}"


class _FakeFormData(dict):
    """request.form()'s return type supports .get(key, default) the same
    way a plain dict does -- this is all replace_catalog_fields uses."""


class _FakeSession:
    """Enough of AsyncSession's surface for replace_catalog_fields: add()
    is a plain no-op (item.fields already reflects new rows via
    SQLAlchemy's in-memory relationship sync -- see module docstring),
    flush() is an async no-op -- item.fields.clear() itself is plain
    Python collection mutation that works with or without a real session
    behind it, which is all these tests need to verify."""

    def add(self, obj):
        pass

    async def flush(self):
        pass


async def test_replace_catalog_fields_skips_blank_rows():
    item = ServiceCatalogItem(name="x", key="x")
    form = _FakeFormData({"field_key_1": "username", "label_1": "Username", "field_type_1": "text"})
    # Row 2 has no field_key_2 at all -- must be skipped, not error.
    await replace_catalog_fields(_FakeSession(), item, form, max_fields=10)
    assert [f.field_key for f in item.fields] == ["username"]
    assert item.fields[0].sort_order == 0


async def test_replace_catalog_fields_preserves_order_and_reassigns_sort_order():
    item = ServiceCatalogItem(name="x", key="x")
    form = _FakeFormData(
        {
            "field_key_3": "domain",
            "label_3": "Domain",
            "field_key_7": "username",
            "label_7": "Username",
        }
    )
    await replace_catalog_fields(_FakeSession(), item, form, max_fields=10)
    # Row order (3 before 7), not alphabetical or submission order.
    assert [f.field_key for f in item.fields] == ["domain", "username"]
    assert [f.sort_order for f in item.fields] == [0, 1]


async def test_replace_catalog_fields_select_options_only_for_select_type():
    item = ServiceCatalogItem(name="x", key="x")
    form = _FakeFormData(
        {
            "field_key_1": "user_type",
            "label_1": "Type",
            "field_type_1": "select",
            "select_options_1": "normal, admin, service",
            "field_key_2": "notes",
            "field_type_2": "text",
            "select_options_2": "ignored, since, not, select",
        }
    )
    await replace_catalog_fields(_FakeSession(), item, form, max_fields=10)
    by_key = {f.field_key: f for f in item.fields}
    assert by_key["user_type"].select_options == ["normal", "admin", "service"]
    assert by_key["notes"].select_options is None


async def test_replace_catalog_fields_source_expression_only_for_regex_or_jsonpath():
    item = ServiceCatalogItem(name="x", key="x")
    form = _FakeFormData(
        {
            "field_key_1": "a",
            "source_document_id_1": "5",
            "source_mode_1": "content",
            "source_expression_1": "should be dropped -- content mode ignores it",
            "field_key_2": "b",
            "source_document_id_2": "5",
            "source_mode_2": "regex",
            "source_expression_2": "^user: (.+)$",
        }
    )
    await replace_catalog_fields(_FakeSession(), item, form, max_fields=10)
    by_key = {f.field_key: f for f in item.fields}
    assert by_key["a"].source_mode == "content"
    assert by_key["a"].source_expression is None
    assert by_key["b"].source_mode == "regex"
    assert by_key["b"].source_expression == "^user: (.+)$"


async def test_replace_catalog_fields_caps_at_max_fields():
    item = ServiceCatalogItem(name="x", key="x")
    form = _FakeFormData({f"field_key_{i}": f"q{i}" for i in range(1, 15)})
    await replace_catalog_fields(_FakeSession(), item, form, max_fields=10)
    assert len(item.fields) == 10


async def test_replace_catalog_fields_replaces_existing_rows():
    item = _item()
    # Seed one existing row the same way an edit's eager-loaded item.fields
    # would already have one -- constructing with catalog_item=item links
    # it in immediately (see module docstring).
    from rain.db.tenant_models import ServiceCatalogField

    ServiceCatalogField(catalog_item=item, field_key="old", label="Old", sort_order=0)
    assert [f.field_key for f in item.fields] == ["old"]

    form = _FakeFormData({"field_key_1": "new", "label_1": "New"})
    await replace_catalog_fields(_FakeSession(), item, form, max_fields=10)
    # "old" is gone entirely, not left alongside "new".
    assert [f.field_key for f in item.fields] == ["new"]


def test_resolved_source_defaults():
    r = ResolvedSource(ok=True)
    assert r.value is None
    assert r.options == []
    assert r.error is None
    assert r.document_label is None
