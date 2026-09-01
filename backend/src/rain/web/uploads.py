"""Local-volume file storage for user uploads: branding assets (the logo,
and the client portal's optional background image). Document attachments
use this same volume behind a small storage abstraction of their own --
see rain.modules.documents.storage.

A branding asset is still always served from local disk (the static
mount at /media/branding, see rain.main) -- that part is unchanged. What
each save_*_upload function also does is write a durable *backup* of it
(restore_*_if_missing reads one back), so it survives a container
recreated with no persistent uploads volume behind it (e.g.
docker-compose.minimal.yml or the single-container `docker run`
quickstart) instead of being gone until someone notices and re-uploads
it. S3 when S3_BUCKET is set (rain.modules.documents.storage's own
S3StorageBackend, reused here under its own "branding" prefix so the two
don't collide); otherwise a row in control.branding_assets
(rain.db.control_models.BrandingAsset, one per asset key) -- Postgres is
the one piece of infrastructure every deployment already has, unlike the
uploads volume this is specifically covering for."""
from __future__ import annotations

import logging
import re
import secrets
from pathlib import Path

from fastapi import UploadFile

from rain.core.config_store import config_store
from rain.db.base import control_session
from rain.db.control_models import BrandingAsset
from rain.modules.documents.storage import S3StorageBackend
from rain.settings import get_settings

logger = logging.getLogger("rain.uploads")

ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/svg+xml", "image/webp"}
MAX_LOGO_BYTES = 5 * 1024 * 1024

# No SVG here -- a "wallpaper" is a photo/graphic, not an icon, and this
# is meant to sit full-bleed behind the portal page (background-size:
# cover), which an SVG's own intrinsic sizing doesn't play nicely with
# as a CSS background-image the way it does as a plain <img>. Bigger
# ceiling than the logo's, deliberately -- a decent-quality background
# photo is routinely a few MB.
ALLOWED_PORTAL_BACKGROUND_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_PORTAL_BACKGROUND_BYTES = 10 * 1024 * 1024

# Fixed per asset, not per-upload -- there's only ever one current logo
# and one current portal background, and each new upload's backup is
# meant to replace the previous one, the same way the local file it
# backs up isn't kept around under its old name either.
_LOGO_BACKUP_KEY = "logo"
_PORTAL_BACKGROUND_BACKUP_KEY = "portal_background"


class UploadError(ValueError):
    pass


def _branding_backup_s3_backend() -> S3StorageBackend | None:
    settings = get_settings()
    if not settings.s3_bucket:
        return None
    return S3StorageBackend(
        bucket=settings.s3_bucket,
        prefix="branding",
        region=settings.s3_region or None,
        endpoint_url=settings.s3_endpoint_url or None,
        access_key_id=settings.s3_access_key_id or None,
        secret_access_key=settings.s3_secret_access_key or None,
    )


async def _backup_branding_asset(asset_key: str, filename: str, content_type: str, data: bytes) -> None:
    """Best-effort: a failure here shouldn't fail the upload itself (the
    local copy -- the one thing actually needed for the asset to render
    right now -- already succeeded by the time this is called), just
    leave this upload no better protected than before this existed."""
    try:
        s3 = _branding_backup_s3_backend()
        if s3 is not None:
            s3.save(asset_key, data)
            return

        async with control_session() as session:
            row = await session.get(BrandingAsset, asset_key)
            if row is None:
                session.add(BrandingAsset(key=asset_key, filename=filename, content_type=content_type, data=data))
            else:
                row.filename = filename
                row.content_type = content_type
                row.data = data
            await session.commit()
    except Exception:
        logger.exception(
            "failed to back up branding asset %r -- it won't survive a lost local copy until the next re-upload",
            asset_key,
        )


async def _read_branding_asset_backup(asset_key: str) -> bytes | None:
    s3 = _branding_backup_s3_backend()
    if s3 is not None:
        try:
            return s3.read(asset_key)
        except Exception:
            return None

    async with control_session() as session:
        row = await session.get(BrandingAsset, asset_key)
        return row.data if row is not None else None


async def _restore_branding_asset_if_missing(*, config_key: str, asset_key: str, label: str) -> None:
    """Shared by restore_logo_if_missing/restore_portal_background_if_missing
    -- called once at startup (rain.main's lifespan, right after
    config_store.load_all() -- needs `config_key`, and the branding_dir
    directory this writes into already exists by then, see rain.main's
    create_app()). A no-op the overwhelming majority of the time: either
    this asset was never uploaded, or the local file is still right
    there (the uploads volume did persist, the common case). Only
    actually restores anything for a deployment whose local disk didn't
    survive being recreated -- see this module's own docstring for
    which ones."""
    path = config_store.get(config_key)
    if not path:
        return

    filename = Path(path).name
    local_path = Path(get_settings().uploads_dir) / "branding" / filename
    if local_path.exists():
        return

    data = await _read_branding_asset_backup(asset_key)
    if data is None:
        logger.warning(
            "%s (%s) is set but there's no local file and no durable backup to restore it from -- "
            "it'll 404 until someone re-uploads it in Admin > Branding",
            config_key,
            path,
        )
        return

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(data)
    logger.info("restored %s (%s) from its durable backup", label, filename)


async def restore_logo_if_missing() -> None:
    await _restore_branding_asset_if_missing(config_key="logo_path", asset_key=_LOGO_BACKUP_KEY, label="branding logo")


async def restore_portal_background_if_missing() -> None:
    await _restore_branding_asset_if_missing(
        config_key="portal_background_path", asset_key=_PORTAL_BACKGROUND_BACKUP_KEY, label="portal background image"
    )


async def _save_branding_upload(
    upload: UploadFile,
    *,
    asset_key: str,
    filename_prefix: str,
    allowed_types: set[str],
    max_bytes: int,
    error_label: str,
) -> str:
    if upload.content_type not in allowed_types:
        raise UploadError(f"unsupported {error_label} type: {upload.content_type}")

    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadError(f"{error_label} file too large (max {max_bytes // (1024 * 1024)}MB)")

    ext = Path(upload.filename or filename_prefix).suffix or ".png"
    filename = f"{filename_prefix}-{secrets.token_hex(8)}{ext}"

    branding_dir = Path(get_settings().uploads_dir) / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    (branding_dir / filename).write_bytes(data)

    await _backup_branding_asset(asset_key, filename, upload.content_type, data)

    return f"/media/branding/{filename}"


async def save_logo_upload(upload: UploadFile) -> str:
    return await _save_branding_upload(
        upload,
        asset_key=_LOGO_BACKUP_KEY,
        filename_prefix="logo",
        allowed_types=ALLOWED_LOGO_TYPES,
        max_bytes=MAX_LOGO_BYTES,
        error_label="logo",
    )


async def save_portal_background_upload(upload: UploadFile) -> str:
    return await _save_branding_upload(
        upload,
        asset_key=_PORTAL_BACKGROUND_BACKUP_KEY,
        filename_prefix="portal-bg",
        allowed_types=ALLOWED_PORTAL_BACKGROUND_TYPES,
        max_bytes=MAX_PORTAL_BACKGROUND_BYTES,
        error_label="portal background image",
    )


_IMPORT_STASH_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def import_stash_path(token: str) -> Path:
    """`token` round-trips through an HTML form field between the preview
    and commit steps (rain.modules.assets.router, rain.modules.tickets.
    router), so it has to be treated as attacker-controlled at this end
    regardless of the fact
    that the preview step only ever generates it via secrets.token_hex(16)
    -- an unvalidated token here let a crafted commit request (e.g.
    token="/etc/passwd" or "../../../etc/passwd") turn this into an
    arbitrary-path read (import_commit reads it) and delete (unlink()
    afterwards) instead of one confined to the import-stash directory.
    Enforcing the exact shape secrets.token_hex(16) actually produces --
    not just Path(token).name -- also rules out a same-directory token
    that happens to collide with something else already staged there."""
    if not _IMPORT_STASH_TOKEN_RE.match(token):
        raise ValueError(f"invalid import stash token: {token!r}")
    stash_dir = Path(get_settings().uploads_dir) / "import-stash"
    stash_dir.mkdir(parents=True, exist_ok=True)
    return stash_dir / f"{token}.bin"
