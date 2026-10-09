"""A trivial, fully stateless math captcha for the public incident
portal (rain.modules.portal.router) -- not a defense against a targeted
human attacker, just enough friction that a generic web-app scanner
(Nessus, ZAP, sqlmap, ...) fuzzing every form on a reachable host
doesn't end up filing hundreds of real tickets. Self-contained (the two
numbers plus an HMAC of them, all round-tripped through hidden form
fields) rather than session-backed, because an anonymous portal visitor
has no session to hold server-side state in to begin with (see that
router module's own docstring)."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from rain.settings import get_settings


def new_challenge() -> tuple[int, int, str]:
    a, b = secrets.randbelow(8) + 1, secrets.randbelow(8) + 1
    return a, b, _sign(a, b)


def verify(a: str, b: str, token: str, answer: str) -> bool:
    """False for anything malformed, not just a wrong sum -- a scanner
    throwing arbitrary fuzz values at every field should fail the same
    way a blank/absent answer does, not raise past this check."""
    try:
        a_int, b_int = int(a), int(b)
        answer_int = int(answer.strip())
    except (TypeError, ValueError, AttributeError):
        return False
    if not hmac.compare_digest(_sign(a_int, b_int), token):
        return False
    return answer_int == a_int + b_int


def _sign(a: int, b: int) -> str:
    key = get_settings().app_secret_key.encode("utf-8")
    return hmac.new(key, f"{a}:{b}".encode("utf-8"), hashlib.sha256).hexdigest()
