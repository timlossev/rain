"""ticket_assignment_changes: audit trail for assignee changes, shown
interleaved with comments/status changes in the ticket detail activity feed

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_assignment_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer, nullable=True),
        sa.Column("from_assignee_user_id", sa.Integer, nullable=True),
        sa.Column("to_assignee_user_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_assignment_changes_ticket_id", "ticket_assignment_changes", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("ticket_assignment_changes")
