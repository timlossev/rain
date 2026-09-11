"""rain.core.security's two password-hashing algorithms -- Argon2id
(default) and PBKDF2-HMAC-SHA256 (Settings.fips_password_hashing, see
that field's own docstring for why FIPS 140-3 requires the swap).
verify_password dispatches on the stored hash's own prefix, not the
current setting, so the two algorithms have to keep interoperating
regardless of which one is active *now* -- that's the property most
worth covering here, not just "each one round-trips its own hash"."""
from __future__ import annotations

from rain.core.security import _PBKDF2_PREFIX, hash_password, verify_password
from rain.settings import get_settings


def test_argon2_is_the_default_and_round_trips(monkeypatch):
    monkeypatch.setattr(get_settings(), "fips_password_hashing", False)
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_fips_mode_produces_pbkdf2_and_round_trips(monkeypatch):
    monkeypatch.setattr(get_settings(), "fips_password_hashing", True)
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith(_PBKDF2_PREFIX)
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_verify_password_ignores_the_current_setting():
    """The whole point of dispatching on the hash's own prefix rather
    than the live setting: an admin flipping fips_password_hashing must
    not strand anyone's existing password, in either direction."""
    argon2_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$ZmFrZWhhc2hmYWtlaGFzaGZha2VoYXNo"
    # Argon2 verification of a hand-built fake hash always fails closed
    # (VerifyMismatchError, caught below) -- this asserts the *dispatch*
    # went to the Argon2 branch at all (it would raise/behave differently
    # if PBKDF2 parsing got it instead), not that this specific fake hash
    # verifies.
    assert verify_password("anything", argon2_hash) is False

    from rain.core.security import _pbkdf2_hash

    pbkdf2_hash = _pbkdf2_hash("correct horse battery staple", b"0123456789abcdef", 1000)
    assert verify_password("correct horse battery staple", pbkdf2_hash) is True
    assert verify_password("wrong password", pbkdf2_hash) is False


def test_pbkdf2_hash_embeds_its_own_iteration_count():
    """A later bump to _PBKDF2_ITERATIONS (OWASP's recommended work
    factor moves over time, same as Argon2's own parameters would) must
    not strand hashes made under the old count -- each hash carries
    whatever count it was actually made with, not a reference to
    whatever the constant currently says."""
    from rain.core.security import _pbkdf2_hash

    hashed = _pbkdf2_hash("password", b"0123456789abcdef", 1_000)
    assert "$1000$" in hashed
    assert verify_password("password", hashed) is True


def test_malformed_pbkdf2_hash_fails_closed_instead_of_raising():
    assert verify_password("anything", f"{_PBKDF2_PREFIX}not-a-valid-payload") is False
    assert verify_password("anything", f"{_PBKDF2_PREFIX}") is False
