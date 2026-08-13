"""correlation_rules / correlation_rule_states: multi-event ("N matching
events within T minutes, optionally per host/program") correlation for
Event Policies, evaluated per-event against syslog_events -- see
rain.modules.tickets.correlation. Ticket gains source_correlation_rule_id
alongside its existing source_rule_id (single-event TicketRule).

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "correlation_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("rule_type", sa.String(15), nullable=False, server_default="threshold"),
        sa.Column("ticket_type", sa.String(15), nullable=False),
        sa.Column("match_field", sa.String(15), nullable=False, server_default="message"),
        sa.Column("pattern", sa.String(500), nullable=False),
        sa.Column("group_by", sa.String(15), nullable=False, server_default="none"),
        sa.Column("threshold_count", sa.Integer, nullable=False, server_default="5"),
        sa.Column("window_minutes", sa.Integer, nullable=False, server_default="5"),
        sa.Column("title_template", sa.String(255), nullable=False, server_default="{count} matching events in {window}m"),
        sa.Column("severity", sa.String(15), nullable=False, server_default="medium"),
        sa.Column("asset_match_field", sa.String(15), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "correlation_rule_states",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rule_id", sa.Integer, sa.ForeignKey("correlation_rules.id", ondelete="CASCADE"), nullable=False),
        # "" (never NULL) for an ungrouped rule -- Postgres unique
        # constraints treat every NULL as distinct, which would defeat
        # both the uniqueness guarantee and the ON CONFLICT upsert in
        # rain.modules.tickets.correlation. See CorrelationRuleState's docstring.
        sa.Column("group_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rule_id", "group_key", name="uq_correlation_rule_states_rule_group"),
    )
    op.create_index("ix_correlation_rule_states_rule_id", "correlation_rule_states", ["rule_id"])

    # add_column() needs schema= explicitly -- see migrations/tenant/
    # script.py.mako's header note (op.add_column doesn't pick up this
    # connection's schema_translate_map on its own).
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "tickets",
        sa.Column("source_correlation_rule_id", sa.Integer, sa.ForeignKey("correlation_rules.id", ondelete="SET NULL")),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("tickets", "source_correlation_rule_id", schema=schema)
    op.drop_table("correlation_rule_states")
    op.drop_table("correlation_rules")
