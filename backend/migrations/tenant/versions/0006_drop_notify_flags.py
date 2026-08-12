"""drop notification_channels.notify_on_incident/notify_on_vulnerability

These drove an unconditional "notify on every ticket of this type" firing
that ran in parallel with Platform Event rules and was a strict subset of
what a rule (pattern ".*", a notify_slack/notify_email action pointed at
the same channel) already covers explicitly. Removed rather than left as
a second, always-on code path -- see rain.modules.tickets.platform_events
and the NotificationChannel model docstring.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tenant_schema() -> str:
    # op.drop_column()/op.add_column() without an explicit schema= emit an
    # unqualified ALTER TABLE that doesn't pick up this connection's
    # schema_translate_map -- confirmed via a real run (UndefinedTableError,
    # same class of bug as 0005's op.bulk_insert -- see its comment). Passing
    # schema= explicitly sidesteps translate_map entirely instead of relying
    # on it.
    return op.get_bind().get_execution_options()["schema_translate_map"][None]


def upgrade() -> None:
    schema = _tenant_schema()
    op.drop_column("notification_channels", "notify_on_incident", schema=schema)
    op.drop_column("notification_channels", "notify_on_vulnerability", schema=schema)


def downgrade() -> None:
    schema = _tenant_schema()
    op.add_column(
        "notification_channels",
        sa.Column("notify_on_incident", sa.Boolean, nullable=False, server_default=sa.text("true")),
        schema=schema,
    )
    op.add_column(
        "notification_channels",
        sa.Column("notify_on_vulnerability", sa.Boolean, nullable=False, server_default=sa.text("true")),
        schema=schema,
    )
