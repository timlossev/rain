"""Local-volume file storage for user uploads (branding logo now; document
repository attachments in Milestone 3 will reuse this same volume behind a
small storage abstraction)."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import UploadFile

from rain.settings import get_settings

ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/svg+xml", "image/webp"}
MAX_LOGO_BYTES = 5 * 1024 * 1024


class UploadError(ValueError):
    pass


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

    return f"/media/branding/{filename}"


def import_stash_path(token: str) -> Path:
    stash_dir = Path(get_settings().uploads_dir) / "import-stash"
    stash_dir.mkdir(parents=True, exist_ok=True)
    return stash_dir / f"{token}.bin"
