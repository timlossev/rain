"""Password hashing and session-token helpers.

Sessions are DB-backed (rain.db.control_models.Session), not JWTs: the
cookie holds an opaque random token, and only its sha256 hash is stored,
so a database leak alone can't be used to forge or replay a session, and
revocation is just a row delete.

Password hashing has two algorithms, not one -- Argon2id (the default)
and PBKDF2-HMAC-SHA256, switched by Settings.fips_password_hashing (see
that field's own docstring for why: Argon2 has no FIPS 140-3 approved
status at all, independent of anything else in this app's crypto
stack). hash_password is the only place the setting is actually read;
verify_password instead dispatches on which prefix the stored hash
itself starts with, so a hash made under one setting still verifies
correctly if the setting is later flipped -- an admin turning FIPS mode
on doesn't strand every existing Argon2 password, it only changes what
the *next* hash_password call produces."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from rain.settings import get_settings

SESSION_COOKIE_NAME = "rain_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days

_hasher = PasswordHasher()

# PBKDF2-HMAC-SHA256, SP 800-132 -- the FIPS-approved alternative to
# Argon2id. 600,000 iterations is OWASP's 2023 recommendation for this
# exact construction; embedded in every hash produced (not just read from
# this constant at verify time) so a later bump to the work factor
# doesn't strand hashes made under the old one -- each hash carries
# whatever count it was actually made with.
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT_BYTES = 16
_PBKDF2_PREFIX = "$pbkdf2-sha256$"


def _pbkdf2_hash(password: str, salt: bytes, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PBKDF2_PREFIX}{iterations}${base64.b64encode(salt).decode('ascii')}${base64.b64encode(digest).decode('ascii')}"


def hash_password(password: str) -> str:
    if get_settings().fips_password_hashing:
        return _pbkdf2_hash(password, os.urandom(_PBKDF2_SALT_BYTES), _PBKDF2_ITERATIONS)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith(_PBKDF2_PREFIX):
        # Own try/except, not folded into the Argon2 one below -- a
        # PBKDF2-shaped hash never reaches _hasher.verify (it would just
        # raise its own, differently-shaped error), and a malformed/
        # truncated stored value here (corrupt row, hand-edited DB) fails
        # closed the same as a real mismatch rather than raising past
        # this function -- same defensive posture the Argon2 branch below
        # already has.
        try:
            iterations_str, salt_b64, digest_b64 = password_hash[len(_PBKDF2_PREFIX) :].split("$")
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(digest_b64)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_str))
        except Exception:
            return False
        return hmac.compare_digest(actual, expected)
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
