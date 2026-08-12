"""Document file storage behind a small abstraction. `LocalStorageBackend`
(a tenant-namespaced subtree of the uploads volume) is the only
implementation today; swapping in an S3-backed one later is a matter of
implementing StorageBackend and changing get_storage() -- no caller
(rain.modules.documents.router) touches the filesystem directly.

Never served through the static file mount (see rain.main's /media/branding
scoping) -- always through the authenticated
GET /documents/{id}/download route.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Protocol

from rain.settings import get_settings


class StorageBackend(Protocol):
    def save(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorageBackend:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


def get_storage() -> StorageBackend:
    return LocalStorageBackend(Path(get_settings().uploads_dir) / "documents")


def make_storage_key(tenant_schema: str, filename: str) -> str:
    # Path(...).name strips any directory components a malicious filename
    # might carry (e.g. "../../etc/passwd"), and the random token keeps
    # concurrent same-name uploads from colliding.
    safe_name = Path(filename or "file").name
    token = secrets.token_hex(8)
    return f"{tenant_schema}/{token}-{safe_name}"
