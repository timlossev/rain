"""approval_flows.notify_syslog_on_approval: opt-in, per-flow checkbox --
when a Change ticket running this flow clears its last approval step, a
synthetic SyslogEvent is emitted (same convention documents.alert_on_change
already uses), which then flows through the normal ticket-rule/
correlation-rule pipeline like any real inbound syslog line.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly to respect this
    # env.py's schema_translate_map -- see the NOTE in script.py.mako.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "approval_flows",
        sa.Column("notify_syslog_on_approval", sa.Boolean, nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("approval_flows", "notify_syslog_on_approval", schema=schema)
