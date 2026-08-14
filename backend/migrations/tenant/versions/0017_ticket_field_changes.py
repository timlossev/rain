"""ticket_field_changes: generic audit trail for simple field edits
(severity, is_chronic, title) that don't warrant their own dedicated
table the way status/assignee/asset changes do -- one row per edit,
shown interleaved in the activity feed.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.create_table() doesn't respect this env.py's schema_translate_map
    # either -- see the NOTE in script.py.mako, hit for real by 0005/0006/
    # 0013/0015/0016.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.create_table(
        "ticket_field_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "ticket_id", sa.Integer, sa.ForeignKey(f"{schema}.tickets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("changed_by_user_id", sa.Integer, nullable=True),
        sa.Column("field_name", sa.String(30), nullable=False),
        sa.Column("from_value", sa.String(255), nullable=True),
        sa.Column("to_value", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=schema,
    )
    op.create_index(
        "ix_ticket_field_changes_ticket_id", "ticket_field_changes", ["ticket_id"], schema=schema
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_index("ix_ticket_field_changes_ticket_id", table_name="ticket_field_changes", schema=schema)
    op.drop_table("ticket_field_changes", schema=schema)
