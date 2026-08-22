from __future__ import annotations

from pathlib import Path

import pytest

from rain.core.config_store import config_store
from rain.settings import get_settings
from rain.web.uploads import restore_logo_if_missing


@pytest.fixture(autouse=True)
def _reset_config_store_cache():
    """restore_logo_if_missing() reads config_store's in-process cache
    directly (no DB round-trip -- see rain.core.config_store.ConfigStore.get),
    which is what makes its early-return paths testable without a live
    Postgres. Snapshot/restore it so a test setting logo_path doesn't leak
    into whichever test runs next."""
    original = dict(config_store._cache)
    yield
    config_store._cache = original


async def test_restore_logo_if_missing_noop_without_a_configured_logo():
    # No logo_path in the cache -> config_store.get() falls back to
    # DEFAULTS' None -- must return before ever needing a DB/S3 backend,
    # neither of which is available in this test.
    config_store._cache.pop("logo_path", None)
    await restore_logo_if_missing()


async def test_restore_logo_if_missing_noop_when_local_file_already_there(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(get_settings(), "uploads_dir", str(tmp_path))
    branding_dir = tmp_path / "branding"
    branding_dir.mkdir()
    local_file = branding_dir / "logo-abc123.png"
    local_file.write_bytes(b"already here")
    config_store._cache["logo_path"] = "/media/branding/logo-abc123.png"

    # The local copy already exists, so this must return before reaching
    # for a durable backup -- if it tried, this would error (no DB/S3
    # available in this test).
    await restore_logo_if_missing()

    assert local_file.read_bytes() == b"already here"
