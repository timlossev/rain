"""Batched control.users id -> display_name lookup, shared by every module
that stores a plain cross-schema user id (ticket comments/status/
assignee/reporter, group memberships, approval decisions, ...) and needs
to resolve a handful of them to a name once per page render rather than
issuing a separate control-schema query per row (see tenant_models'
module docstring for why those references are plain integers, not real
FKs, in the first place)."""
from __future__ import annotations

from sqlalchemy import select

from rain.db.base import control_session
from rain.db.control_models import User


async def resolve_user_names(user_ids: set[int | None]) -> dict[int, str]:
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    async with control_session() as session:
        result = await session.execute(select(User).where(User.id.in_(ids)))
        return {u.id: u.display_name for u in result.scalars()}


async def is_assignable_user(user_id: int, tenant_id: int) -> bool:
    """True iff `user_id` is someone `tenant_id` is actually allowed to
    hand a ticket/group-membership/approval-step to -- that tenant's own
    users, plus internal_admin (platform-wide, not tenant-scoped). Same
    predicate rain.modules.tickets.router.search_assignable_users already
    uses to build the picker's own candidate list; call sites that
    *write* a user id (assign_ticket, group membership, approval steps)
    need to re-apply it server-side too, not just trust that whatever
    arrived came from that same picker -- a plain integer form field
    doesn't carry the search route's own tenant scoping with it."""
    async with control_session() as session:
        result = await session.execute(
            select(User).where(
                User.id == user_id,
                User.is_active.is_(True),
                (User.tenant_id == tenant_id) | (User.role_key == "internal_admin"),
            )
        )
        return result.scalar_one_or_none() is not None


async def list_assignable_users(tenant_id: int) -> list[User]:
    """Every user is_assignable_user above would accept for `tenant_id` --
    this tenant's own active users plus every active internal_admin
    (platform-wide, not tenant-scoped) -- ordered by display name. Backs
    Kanban's "group by assignee" view (rain.modules.tickets.router.
    kanban_board), which needs the full candidate list up front, unlike
    rain.modules.tickets.router.search_assignable_users' typed-a-few-
    characters, capped-at-8 predictive search."""
    async with control_session() as session:
        stmt = (
            select(User)
            .where(User.is_active.is_(True), (User.tenant_id == tenant_id) | (User.role_key == "internal_admin"))
            .order_by(User.display_name)
        )
        result = await session.execute(stmt)
        return list(result.scalars())


async def resolve_user_emails(user_ids: set[int | None]) -> dict[int, str]:
    """Same batched lookup as resolve_user_names, but for email addresses --
    backs notification-trigger code (approval-pending emails, ticket
    watchers) that needs a recipient address rather than a display name."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    async with control_session() as session:
        result = await session.execute(select(User).where(User.id.in_(ids)))
        return {u.id: u.email for u in result.scalars()}
