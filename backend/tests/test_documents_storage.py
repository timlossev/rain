from __future__ import annotations

from pathlib import Path

from rain.modules.documents.storage import LocalStorageBackend, make_storage_key


def test_make_storage_key_namespaces_by_tenant():
    key = make_storage_key("tenant_acme", "runbook.pdf")
    assert key.startswith("tenant_acme/")
    assert key.endswith("-runbook.pdf")


def test_make_storage_key_strips_path_traversal():
    key = make_storage_key("tenant_acme", "../../etc/passwd")
    assert "/../" not in key
    assert key.split("/", 1)[1].endswith("-passwd")


def test_make_storage_key_is_unique_per_call():
    a = make_storage_key("tenant_acme", "same-name.txt")
    b = make_storage_key("tenant_acme", "same-name.txt")
    assert a != b


def test_local_storage_backend_roundtrip(tmp_path: Path):
    backend = LocalStorageBackend(tmp_path)
    key = "tenant_acme/abc123-file.txt"
    backend.save(key, b"hello world")
    assert backend.read(key) == b"hello world"
    backend.delete(key)
    assert not (tmp_path / key).exists()
