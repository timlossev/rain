"""Thin synchronous wrapper around ldap3 (pure Python -- no system libldap,
so this doesn't touch the Alpine image's Dockerfile at all, unlike
python-ldap which needs libldap2-dev to build).

ldap3 itself is a blocking library end to end (its own docs recommend
threads, not asyncio, for concurrency). Every function here is a plain
blocking call -- callers in an async context (rain.modules.auth.provider,
rain.modules.auth.ldap_sync) are expected to run them via
asyncio.to_thread(), never directly on the event loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ldap3 import ALL, SIMPLE, Connection, Server
from ldap3.core.exceptions import LDAPException

logger = logging.getLogger("rain.ldap")


@dataclass(frozen=True)
class LdapUser:
    dn: str
    email: str
    display_name: str


@dataclass(frozen=True)
class LdapGroup:
    dn: str
    name: str
    member_dns: list[str]


def _server(server_uri: str) -> Server:
    use_ssl = server_uri.startswith("ldaps://")
    host = server_uri.split("://", 1)[-1]
    return Server(host, use_ssl=use_ssl, get_info=ALL)


def _bind(server_uri: str, bind_dn: str, bind_password: str, use_starttls: bool) -> Connection:
    """Raises ldap3.core.exceptions.LDAPException (or a subclass) on any
    connection/bind failure -- callers decide whether that means "reject
    this login" (authenticate_user) or "surface an error" (test_bind,
    the sync loop)."""
    conn = Connection(
        _server(server_uri), user=bind_dn, password=bind_password, authentication=SIMPLE, auto_bind=False
    )
    if use_starttls:
        conn.open()
        conn.start_tls()
    if not conn.bind():
        detail = conn.result.get("description") or conn.result.get("message") or "bind failed"
        raise LDAPException(detail)
    return conn


def test_bind(server_uri: str, bind_dn: str, bind_password: str, use_starttls: bool = False) -> None:
    """Used by the "Test connection" admin action. Raises on failure."""
    _bind(server_uri, bind_dn, bind_password, use_starttls).unbind()


def authenticate_user(server_uri: str, user_dn: str, password: str, use_starttls: bool = False) -> bool:
    """The actual login-time credential check: bind AS the user with the
    password they just submitted. RAIN never stores or otherwise sees this
    password beyond the single bind attempt. Returns False (never raises)
    on any failure -- a malformed directory response is exactly as much
    "not authenticated" as a wrong password from the caller's perspective."""
    if not password:
        return False
    try:
        _bind(server_uri, user_dn, password, use_starttls).unbind()
        return True
    except LDAPException:
        return False


def _first_attr(attrs: dict, key: str) -> str | None:
    values = attrs.get(key)
    if not values:
        return None
    return str(values[0])


def search_users(
    server_uri: str,
    bind_dn: str,
    bind_password: str,
    base_dn: str,
    filter_: str,
    email_attr: str,
    name_attr: str,
    *,
    use_starttls: bool = False,
) -> list[LdapUser]:
    conn = _bind(server_uri, bind_dn, bind_password, use_starttls)
    try:
        conn.search(base_dn, filter_, attributes=[email_attr, name_attr])
        users: list[LdapUser] = []
        for entry in conn.entries:
            attrs = entry.entry_attributes_as_dict
            email = _first_attr(attrs, email_attr)
            name = _first_attr(attrs, name_attr)
            if not email:
                logger.warning("LDAP entry %s has no %s attribute -- skipped", entry.entry_dn, email_attr)
                continue
            users.append(LdapUser(dn=entry.entry_dn, email=email.strip().lower(), display_name=name or email))
        return users
    finally:
        conn.unbind()


def search_groups(
    server_uri: str,
    bind_dn: str,
    bind_password: str,
    base_dn: str,
    filter_: str,
    name_attr: str,
    member_attr: str,
    *,
    use_starttls: bool = False,
) -> list[LdapGroup]:
    conn = _bind(server_uri, bind_dn, bind_password, use_starttls)
    try:
        conn.search(base_dn, filter_, attributes=[name_attr, member_attr])
        groups: list[LdapGroup] = []
        for entry in conn.entries:
            attrs = entry.entry_attributes_as_dict
            name = _first_attr(attrs, name_attr)
            if not name:
                logger.warning("LDAP entry %s has no %s attribute -- skipped", entry.entry_dn, name_attr)
                continue
            member_dns = [str(v) for v in (attrs.get(member_attr) or [])]
            groups.append(LdapGroup(dn=entry.entry_dn, name=name, member_dns=member_dns))
        return groups
    finally:
        conn.unbind()
