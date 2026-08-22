"""Document file storage behind a small abstraction. `LocalStorageBackend`
(a tenant-namespaced subtree of the uploads volume) and `S3StorageBackend`
(any S3-compatible bucket -- real AWS S3, or a self-hosted one like MinIO)
both implement StorageBackend; get_storage() picks one based on Settings.
No caller (rain.modules.documents.router/service) touches the filesystem
or an S3 client directly, so a third backend later is the same drill:
implement StorageBackend, extend get_storage()'s dispatch.

Never served through the static file mount (see rain.main's /media/branding
scoping) -- always through the authenticated
GET /documents/{id}/download route.

Scope: this is document bodies only -- rain.web.uploads reuses
S3StorageBackend for its own, separate purpose (backing up the branding
logo under its own "branding" prefix in the same bucket), but doesn't go
through get_storage() to do it, since a logo is always served straight
off the local static mount regardless of s3_bucket (an S3 object can't
be, without a signed-URL redirect this app doesn't have) -- S3 there is
only ever a backup to restore the local copy from, never the read path
itself. The CSV/JSON import stash stays on local disk unconditionally
too, being transient by design (gone once the import finishes, nothing
to back up). See Settings.s3_bucket's own docstring.
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


class S3StorageBackend:
    """Synchronous (boto3, not aioboto3) to match StorageBackend's existing
    signature exactly -- every caller already invokes save/read/delete as
    plain blocking calls from inside an async route handler (the same
    trade-off LocalStorageBackend's disk I/O already makes), so this
    doesn't change that shape, just what's on the other end of it.

    One client per backend instance, not per call -- boto3 clients are
    thread-safe and hold onto a connection pool, so building a fresh one
    per save/read/delete would throw that away for no benefit. get_storage()
    is called per-request rather than cached at import time, though: a
    fresh Settings read every time keeps this consistent with every other
    call site of get_settings(), and constructing a boto3 client is cheap
    (no network I/O happens until the first real request against it)."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "documents",
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        import boto3

        self._bucket = bucket
        self._prefix = prefix
        client_kwargs: dict = {}
        if region:
            client_kwargs["region_name"] = region
        if endpoint_url:
            # What makes this work against any S3-compatible service
            # (MinIO, etc.), not just real AWS S3 -- leave unset for AWS.
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key_id and secret_access_key:
            client_kwargs["aws_access_key_id"] = access_key_id
            client_kwargs["aws_secret_access_key"] = secret_access_key
        # Else: falls back to boto3's normal credential chain (instance/
        # task IAM role, ~/.aws/credentials, AWS_* env vars) -- no static
        # pair required for a real AWS deployment that already has one of
        # those, only for a self-hosted S3-compatible service that needs
        # an explicit key pair.
        self._client = boto3.client("s3", **client_kwargs)

    def _object_key(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def save(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._object_key(key), Body=data)

    def read(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=self._object_key(key))
        return response["Body"].read()

    def delete(self, key: str) -> None:
        # S3 DeleteObject is idempotent (204 whether or not the key
        # existed) -- same "no-op on a missing object" contract
        # LocalStorageBackend.delete's missing_ok=True gives callers.
        self._client.delete_object(Bucket=self._bucket, Key=self._object_key(key))


def get_storage() -> StorageBackend:
    settings = get_settings()
    if settings.s3_bucket:
        return S3StorageBackend(
            bucket=settings.s3_bucket,
            region=settings.s3_region or None,
            endpoint_url=settings.s3_endpoint_url or None,
            access_key_id=settings.s3_access_key_id or None,
            secret_access_key=settings.s3_secret_access_key or None,
        )
    return LocalStorageBackend(Path(settings.uploads_dir) / "documents")


def make_storage_key(tenant_schema: str, filename: str) -> str:
    # Path(...).name strips any directory components a malicious filename
    # might carry (e.g. "../../etc/passwd"), and the random token keeps
    # concurrent same-name uploads from colliding.
    safe_name = Path(filename or "file").name
    token = secrets.token_hex(8)
    return f"{tenant_schema}/{token}-{safe_name}"
