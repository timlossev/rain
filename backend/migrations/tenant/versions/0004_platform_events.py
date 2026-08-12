"""platform events: rules that react to ticket-creation events with one or
more actions (notify Slack/email, call a webhook, attach a document/asset),
plus a per-ticket trigger log (Milestone 2 follow-up)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_event_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("trigger_event", sa.String(31), nullable=False),
        sa.Column("match_field", sa.String(15), nullable=False, server_default="title"),
        sa.Column("pattern", sa.String(500), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "platform_event_actions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rule_id", sa.Integer, sa.ForeignKey("platform_event_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(31), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_platform_event_actions_rule_id", "platform_event_actions", ["rule_id"])

    op.create_table(
        "platform_event_triggers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rule_id", sa.Integer, sa.ForeignKey("platform_event_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rule_name", sa.String(255), nullable=False),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_platform_event_triggers_ticket_id", "platform_event_triggers", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("platform_event_triggers")
    op.drop_table("platform_event_actions")
    op.drop_table("platform_event_rules")
