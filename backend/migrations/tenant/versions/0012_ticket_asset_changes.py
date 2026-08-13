"""ticket_asset_changes: audit trail for a ticket's affected-asset changes,
shown interleaved with comments/status/assignment changes in the ticket
detail activity feed

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_asset_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer, nullable=True),
        sa.Column("from_asset_id", sa.Integer, sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_asset_id", sa.Integer, sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_asset_changes_ticket_id", "ticket_asset_changes", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("ticket_asset_changes")
