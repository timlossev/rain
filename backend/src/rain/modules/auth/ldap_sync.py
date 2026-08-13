"""Periodic LDAP -> local-storage sync: pulls users and groups from the
configured directory (rain.modules.auth.ldap_config) into control.users
and the target tenant's Group/GroupMembership tables.

Mirrors rain.modules.calendar.sweep's run_once() + *_loop() shape: a
plain function the Admin "Sync now" button can also call directly for an
on-demand run, wrapped by a loop that sleeps between runs in the worker.

Ownership rule that makes re-running this safe: a User this sync creates
gets auth_source="ldap"; a Group it creates gets source="ldap" and
ldap_dn set. Every later run only ever touches rows it owns (matched by
ldap_dn, or by auth_source=="ldap" for the deactivation sweep) --
a manually created local user or group, even one with a colliding email
or name, is never touched.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import select

from rain.core import ldap_client
from rain.db.base import control_session, tenant_session
from rain.db.control_models import Tenant, User
from rain.db.tenant_models import Group, GroupMembership
from rain.modules.auth.ldap_config import get_ldap_config, get_provider_row

logger = logging.getLogger("rain.ldap_sync")

DEFAULT_INTERVAL_MINUTES = 60


async def run_ldap_sync() -> str:
    """Returns a one-line human-readable summary, which is also what gets
    stored as auth_providers.last_sync_summary -- errors included, so a
    failed run is visible in the Admin UI without digging through logs."""
    async with control_session() as session:
        config = await get_ldap_config(session)
        if config is None:
            return "Not configured or not enabled -- nothing to sync."

        tenant = await session.get(Tenant, config.target_tenant_id)
        if tenant is None or not tenant.is_active:
            return f"Target tenant id {config.target_tenant_id} doesn't exist or is inactive -- sync skipped."

        try:
            ldap_users = await asyncio.to_thread(
                ldap_client.search_users,
                config.server_uri,
                config.bind_dn,
                config.bind_password,
                config.user_base_dn,
                config.user_filter,
                config.user_email_attr,
                config.user_name_attr,
                use_starttls=config.use_starttls,
            )
            ldap_groups = await asyncio.to_thread(
                ldap_client.search_groups,
                config.server_uri,
                config.bind_dn,
                config.bind_password,
                config.group_base_dn,
                config.group_filter,
                config.group_name_attr,
                config.group_member_attr,
                use_starttls=config.use_starttls,
            )
        except Exception as exc:
            logger.exception("LDAP sync: directory search failed")
            summary = f"Failed: {exc}"
            await _record_result(session, summary)
            return summary

        dn_to_user_id = await _sync_users(session, ldap_users, config.target_tenant_id)
        n_new = sum(1 for u in ldap_users if u.dn not in dn_to_user_id or dn_to_user_id[u.dn] is None)
        n_deactivated = await _deactivate_missing_users(session, {u.dn for u in ldap_users})

        n_groups = 0
        async with tenant_session(tenant.schema_name) as tenant_db:
            n_groups = await _sync_groups(tenant_db, ldap_groups, dn_to_user_id)
            await _delete_missing_groups(tenant_db, {g.dn for g in ldap_groups})

        summary = (
            f"{len(ldap_users)} users ({n_deactivated} deactivated), "
            f"{n_groups} groups synced into {tenant.name} at "
            f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        await _record_result(session, summary)
        return summary


async def _record_result(session, summary: str) -> None:
    row = await get_provider_row(session)
    if row is not None:
        row.last_synced_at = dt.datetime.now(dt.timezone.utc)
        row.last_sync_summary = summary
        await session.commit()


async def _sync_users(session, ldap_users, target_tenant_id: int) -> dict[str, int | None]:
    """Upserts control.users, matched first by ldap_dn (the stable
    directory identity), falling back to email only to detect -- and skip
    -- a collision with an existing local account rather than silently
    taking it over. Returns {dn: user_id} for every successfully
    synced user, used by the group-membership sync below."""
    dn_to_id: dict[str, int | None] = {}
    for lu in ldap_users:
        result = await session.execute(select(User).where(User.ldap_dn == lu.dn))
        user = result.scalar_one_or_none()

        if user is None:
            result = await session.execute(select(User).where(User.email == lu.email))
            existing_by_email = result.scalar_one_or_none()
            if existing_by_email is not None and existing_by_email.auth_source != "ldap":
                logger.warning(
                    "LDAP sync: %s already exists as a local account (email collision) -- skipped", lu.email
                )
                dn_to_id[lu.dn] = None
                continue
            user = existing_by_email

        if user is None:
            user = User(
                email=lu.email,
                display_name=lu.display_name,
                role_key="client",
                tenant_id=target_tenant_id,
                auth_source="ldap",
                ldap_dn=lu.dn,
                password_hash=None,
                is_active=True,
            )
            session.add(user)
            await session.flush()
        else:
            user.email = lu.email
            user.display_name = lu.display_name
            user.auth_source = "ldap"
            user.ldap_dn = lu.dn
            user.tenant_id = target_tenant_id
            user.is_active = True

        dn_to_id[lu.dn] = user.id

    await session.commit()
    return dn_to_id


async def _deactivate_missing_users(session, present_dns: set[str]) -> int:
    result = await session.execute(select(User).where(User.auth_source == "ldap", User.is_active.is_(True)))
    count = 0
    for user in result.scalars():
        if user.ldap_dn not in present_dns:
            user.is_active = False
            count += 1
    if count:
        await session.commit()
    return count


async def _sync_groups(tenant_db, ldap_groups, dn_to_user_id: dict[str, int | None]) -> int:
    for lg in ldap_groups:
        result = await tenant_db.execute(select(Group).where(Group.ldap_dn == lg.dn))
        group = result.scalar_one_or_none()
        if group is None:
            group = Group(name=lg.name, source="ldap", ldap_dn=lg.dn)
            tenant_db.add(group)
            await tenant_db.flush()
        else:
            group.name = lg.name

        # Replace-all: membership rows aren't referenced by anything else
        # long-term, so a delete-then-reinsert each run is simpler than
        # diffing and just as correct.
        existing = await tenant_db.execute(select(GroupMembership).where(GroupMembership.group_id == group.id))
        for row in existing.scalars():
            await tenant_db.delete(row)

        member_ids = {dn_to_user_id[dn] for dn in lg.member_dns if dn_to_user_id.get(dn)}
        for user_id in member_ids:
            tenant_db.add(GroupMembership(group_id=group.id, user_id=user_id))

    await tenant_db.commit()
    return len(ldap_groups)


async def _delete_missing_groups(tenant_db, present_dns: set[str]) -> None:
    result = await tenant_db.execute(select(Group).where(Group.source == "ldap"))
    to_delete = [g for g in result.scalars() if g.ldap_dn not in present_dns]
    for group in to_delete:
        await tenant_db.delete(group)
    if to_delete:
        await tenant_db.commit()


async def ldap_sync_loop() -> None:
    while True:
        try:
            summary = await run_ldap_sync()
            logger.info("LDAP sync: %s", summary)
        except Exception:
            logger.exception("LDAP sync loop iteration failed unexpectedly")

        async with control_session() as session:
            config = await get_ldap_config(session)
        interval_minutes = config.sync_interval_minutes if config else DEFAULT_INTERVAL_MINUTES
        await asyncio.sleep(max(5, interval_minutes) * 60)
