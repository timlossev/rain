"""Password hashing and session-token helpers.

Sessions are DB-backed (rain.db.control_models.Session), not JWTs: the
cookie holds an opaque random token, and only its sha256 hash is stored,
so a database leak alone can't be used to forge or replay a session, and
revocation is just a row delete.
"""
from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

SESSION_COOKIE_NAME = "rain_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Same construction as the session token pair above -- kept as separate,
# domain-named functions rather than reused directly so a call site reads
# as "a password-reset token" rather than "a session token" repurposed
# for something else, even though the underlying primitives are
# identical (opaque random value, only its hash ever stored).
def new_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
