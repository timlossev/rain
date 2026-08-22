"""Local-volume file storage for user uploads (branding logo now; document
repository attachments in Milestone 3 will reuse this same volume behind a
small storage abstraction).

The logo is still always served from local disk (the static mount at
/media/branding, see rain.main) -- that part is unchanged. What's new is
a durable *backup* of it (save_logo_upload writes one on every upload;
restore_logo_if_missing reads one back), so it survives a container
recreated with no persistent uploads volume behind it (e.g.
docker-compose.minimal.yml or the single-container `docker run`
quickstart) instead of being gone until someone notices and re-uploads
it. S3 when S3_BUCKET is set (rain.modules.documents.storage's own
S3StorageBackend, reused here under its own "branding" prefix so the two
don't collide); otherwise a single row in control.branding_assets
(rain.db.control_models.BrandingAsset) -- Postgres is the one piece of
infrastructure every deployment already has, unlike the uploads volume
this is specifically covering for."""
from __future__ import annotations

import logging
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

# Fixed, not per-upload -- there's only ever one current logo, and each
# new upload's backup is meant to replace the previous one, the same way
# the local file it backs up isn't kept around under its old name either.
_LOGO_BACKUP_KEY = "logo"


class UploadError(ValueError):
    pass


def _logo_backup_s3_backend() -> S3StorageBackend | None:
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


async def _backup_logo(filename: str, content_type: str, data: bytes) -> None:
    """Best-effort: a failure here shouldn't fail the upload itself (the
    local copy -- the one thing actually needed for the logo to render
    right now -- already succeeded by the time this is called), just
    leave this upload no better protected than before this existed."""
    try:
        s3 = _logo_backup_s3_backend()
        if s3 is not None:
            s3.save(_LOGO_BACKUP_KEY, data)
            return

        async with control_session() as session:
            row = await session.get(BrandingAsset, _LOGO_BACKUP_KEY)
            if row is None:
                session.add(BrandingAsset(key=_LOGO_BACKUP_KEY, filename=filename, content_type=content_type, data=data))
            else:
                row.filename = filename
                row.content_type = content_type
                row.data = data
            await session.commit()
    except Exception:
        logger.exception("failed to back up branding logo -- it won't survive a lost local copy until the next re-upload")


async def _read_logo_backup() -> bytes | None:
    s3 = _logo_backup_s3_backend()
    if s3 is not None:
        try:
            return s3.read(_LOGO_BACKUP_KEY)
        except Exception:
            return None

    async with control_session() as session:
        row = await session.get(BrandingAsset, _LOGO_BACKUP_KEY)
        return row.data if row is not None else None


async def restore_logo_if_missing() -> None:
    """Called once at startup (rain.main's lifespan, right after
    config_store.load_all() -- needs logo_path, and the branding_dir
    directory this writes into already exists by then, see rain.main's
    create_app()). A no-op the overwhelming majority of the time: either
    there was never a logo, or the local file is still right there (the
    uploads volume did persist, the common case). Only actually restores
    anything for a deployment whose local disk didn't survive being
    recreated -- see this module's own docstring for which ones."""
    logo_path = config_store.get("logo_path")
    if not logo_path:
        return

    filename = Path(logo_path).name
    local_path = Path(get_settings().uploads_dir) / "branding" / filename
    if local_path.exists():
        return

    data = await _read_logo_backup()
    if data is None:
        logger.warning(
            "logo_path (%s) is set but there's no local file and no durable backup to restore it from -- "
            "it'll 404 until someone re-uploads it in Admin > Branding",
            logo_path,
        )
        return

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(data)
    logger.info("restored branding logo (%s) from its durable backup", filename)


async def save_logo_upload(upload: UploadFile) -> str:
    if upload.content_type not in ALLOWED_LOGO_TYPES:
        raise UploadError(f"unsupported logo type: {upload.content_type}")

    data = await upload.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise UploadError("logo file too large (max 5MB)")

    ext = Path(upload.filename or "logo").suffix or ".png"
    filename = f"logo-{secrets.token_hex(8)}{ext}"

    branding_dir = Path(get_settings().uploads_dir) / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    (branding_dir / filename).write_bytes(data)

    await _backup_logo(filename, upload.content_type, data)

    return f"/media/branding/{filename}"


def import_stash_path(token: str) -> Path:
    stash_dir = Path(get_settings().uploads_dir) / "import-stash"
    stash_dir.mkdir(parents=True, exist_ok=True)
    return stash_dir / f"{token}.bin"
