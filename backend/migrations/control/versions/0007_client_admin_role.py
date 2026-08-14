"""Adds the client_admin role: pinned to one tenant exactly like `client`
(rain.core.tenancy.CurrentUser.is_internal_admin is false for both), but
also passes rain.core.rbac.require_admin -- full admin rights over that
one tenant's own tenant-scoped settings (Ticket Statuses, Notification
Channels, Groups, Approval Flows, Webhooks, Event Promotion Policies,
Correlation Rules, Platform Response Rules). Platform-wide settings
(branding, tenants, users, auth providers, SMTP relay, syslog routing)
stay internal_admin-only, unaffected by this role.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-15

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.roles (key, name, description, permissions) VALUES
        ('client_admin', 'Client Admin',
         'Full admin rights scoped to their own tenant''s settings (rules, flows, groups, channels, webhooks) -- not platform-wide settings.',
         '["tenant:*", "tenant-admin:*"]'::jsonb)
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM {SCHEMA}.roles WHERE key = 'client_admin'")
