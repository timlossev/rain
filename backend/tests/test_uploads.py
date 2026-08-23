from __future__ import annotations

from pathlib import Path

import pytest

from rain.core.config_store import config_store
from rain.settings import get_settings
from rain.web.uploads import restore_logo_if_missing, restore_portal_background_if_missing

# (config key, restore function, a filename shaped like what that
# upload's own save_*_upload would actually generate) -- both restore
# functions share the same underlying _restore_branding_asset_if_missing,
# parametrized here so the two no-DB-needed early-return paths are
# proven for both assets, not just the logo.
_BRANDING_ASSETS = [
    ("logo_path", restore_logo_if_missing, "logo-abc123.png"),
    ("portal_background_path", restore_portal_background_if_missing, "portal-bg-abc123.jpg"),
]


@pytest.fixture(autouse=True)
def _reset_config_store_cache():
    """restore_*_if_missing() reads config_store's in-process cache
    directly (no DB round-trip -- see rain.core.config_store.ConfigStore.get),
    which is what makes its early-return paths testable without a live
    Postgres. Snapshot/restore it so a test setting a path doesn't leak
    into whichever test runs next."""
    original = dict(config_store._cache)
    yield
    config_store._cache = original


@pytest.mark.parametrize("config_key,restore_fn,filename", _BRANDING_ASSETS)
async def test_restore_branding_asset_if_missing_noop_without_one_configured(config_key, restore_fn, filename):
    # No path in the cache -> config_store.get() falls back to DEFAULTS'
    # None -- must return before ever needing a DB/S3 backend, neither of
    # which is available in this test.
    config_store._cache.pop(config_key, None)
    await restore_fn()


@pytest.mark.parametrize("config_key,restore_fn,filename", _BRANDING_ASSETS)
async def test_restore_branding_asset_if_missing_noop_when_local_file_already_there(
    config_key, restore_fn, filename, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(get_settings(), "uploads_dir", str(tmp_path))
    branding_dir = tmp_path / "branding"
    branding_dir.mkdir()
    local_file = branding_dir / filename
    local_file.write_bytes(b"already here")
    config_store._cache[config_key] = f"/media/branding/{filename}"

    # The local copy already exists, so this must return before reaching
    # for a durable backup -- if it tried, this would error (no DB/S3
    # available in this test).
    await restore_fn()

    assert local_file.read_bytes() == b"already here"
