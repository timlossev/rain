"""ticket_watchers -- users who opted in to email notifications for a
ticket's activity (new comments, status changes) beyond the automatic set
(assignee, reporter, pending approvers), toggled via the "Watch" button on
the ticket detail page.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_watchers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        # control.users id -- cross-schema, plain integer per this project's
        # documented schema-per-tenant trade-off (see tenant_models.py docstring).
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticket_id", "user_id", name="uq_ticket_watchers_ticket_user"),
    )
    op.create_index("ix_ticket_watchers_ticket_id", "ticket_watchers", ["ticket_id"])
    op.create_index("ix_ticket_watchers_user_id", "ticket_watchers", ["user_id"])


def downgrade() -> None:
    op.drop_table("ticket_watchers")
