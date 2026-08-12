"""ticketing: syslog events, rules, tickets, comments, notifications (Milestone 2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19

tickets and syslog_events reference each other (a promoted event points at
its ticket; a rule-created ticket points back at its source event), so
syslog_events.promoted_ticket_id is created without its FK and wired up
with op.create_foreign_key once both tables exist.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_config",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer, nullable=True),
    )

    op.create_table(
        "ticket_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("ticket_type", sa.String(15), nullable=False),
        sa.Column("match_field", sa.String(15), nullable=False, server_default="message"),
        sa.Column("pattern", sa.String(500), nullable=False),
        sa.Column("title_template", sa.String(255), nullable=False, server_default="{message}"),
        sa.Column("severity", sa.String(15), nullable=False, server_default="medium"),
        sa.Column("asset_match_field", sa.String(15), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "syslog_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("program", sa.String(255), nullable=True),
        sa.Column("facility", sa.Integer, nullable=True),
        sa.Column("severity", sa.Integer, nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("raw", sa.Text, nullable=False),
        sa.Column("promoted_ticket_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_syslog_events_received_at", "syslog_events", ["received_at"])

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_number", sa.String(31), nullable=False),
        sa.Column("ticket_type", sa.String(15), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(15), nullable=False, server_default="medium"),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_event_id", sa.Integer, sa.ForeignKey("syslog_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_rule_id", sa.Integer, sa.ForeignKey("ticket_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assignee_user_id", sa.Integer, nullable=True),
        sa.Column("reporter_user_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("ticket_number", name="uq_tickets_ticket_number"),
    )
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    op.create_foreign_key(
        "fk_syslog_events_promoted_ticket_id",
        "syslog_events",
        "tickets",
        ["promoted_ticket_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer, nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_comments_ticket_id", "ticket_comments", ["ticket_id"])

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("channel_type", sa.String(15), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("notify_on_incident", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("notify_on_vulnerability", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_sequence("inc_number_seq")
    op.create_sequence("vuln_number_seq")


def downgrade() -> None:
    op.drop_sequence("vuln_number_seq")
    op.drop_sequence("inc_number_seq")
    op.drop_table("notification_channels")
    op.drop_table("ticket_comments")
    op.drop_constraint("fk_syslog_events_promoted_ticket_id", "syslog_events", type_="foreignkey")
    op.drop_table("tickets")
    op.drop_table("syslog_events")
    op.drop_table("ticket_rules")
    op.drop_table("tenant_config")
