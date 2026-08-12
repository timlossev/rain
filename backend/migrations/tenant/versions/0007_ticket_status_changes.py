"""ticket_status_changes: audit trail for status transitions, shown
interleaved with comments in the ticket detail activity feed

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_status_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer, nullable=True),
        sa.Column("from_status", sa.String(31), nullable=True),
        sa.Column("to_status", sa.String(31), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_status_changes_ticket_id", "ticket_status_changes", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("ticket_status_changes")
