"""Symmetric encryption for sensitive config-at-rest (e.g. the SMTP relay
password, notification channel webhook URLs, and the LDAP bind password).

The Fernet key is derived from APP_SECRET_KEY rather than stored
separately -- one bootstrap secret to manage, not two.
"""
from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet

from rain.settings import get_settings


@lru_cache
def _fernet() -> Fernet:
    key_material = hashlib.sha256(get_settings().app_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


def encrypt_json(data: Any) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode("utf-8"))


def decrypt_json(ciphertext: bytes) -> Any:
    return json.loads(_fernet().decrypt(ciphertext).decode("utf-8"))
