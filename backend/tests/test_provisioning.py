from __future__ import annotations

import pytest

from rain.db.provisioning import _SLUG_RE, schema_name_for


@pytest.mark.parametrize("slug", ["acme", "acme_corp", "ab1"])
def test_valid_slugs(slug):
    assert _SLUG_RE.match(slug)


@pytest.mark.parametrize("slug", ["Acme", "1acme", "ac me", "a", ""])
def test_invalid_slugs(slug):
    assert not _SLUG_RE.match(slug)


def test_schema_name_for():
    assert schema_name_for("acme") == "tenant_acme"
