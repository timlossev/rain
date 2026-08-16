"""Correlation Rules: a second rule_type, "ml_anomaly" (alongside the
existing "threshold"), backed by a per rule+group river.anomaly.HalfSpaceTrees
model persisted on correlation_rule_states. Adds ml_score_threshold/
ml_warmup_count config to correlation_rules and ml_model/ml_event_count
state to correlation_rule_states; correlation_rule_states.last_triggered_at
becomes nullable (an ml_anomaly group's state row exists -- and needs to
persist its model -- from its very first event, well before it has ever
fired a ticket, unlike a "threshold" row which is only ever created at
first fire).

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.alter_column() need schema= passed explicitly to
    # respect this env.py's schema_translate_map -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0028.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "correlation_rules",
        sa.Column("ml_score_threshold", sa.Float, nullable=False, server_default="0.7"),
        schema=schema,
    )
    op.add_column(
        "correlation_rules",
        sa.Column("ml_warmup_count", sa.Integer, nullable=False, server_default="250"),
        schema=schema,
    )

    op.add_column(
        "correlation_rule_states",
        sa.Column("ml_model", sa.LargeBinary, nullable=True),
        schema=schema,
    )
    op.add_column(
        "correlation_rule_states",
        sa.Column("ml_event_count", sa.Integer, nullable=False, server_default="0"),
        schema=schema,
    )
    op.alter_column(
        "correlation_rule_states",
        "last_triggered_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    # A null last_triggered_at (only possible from an ml_anomaly group
    # that hasn't fired yet) has no meaningful "threshold" equivalent --
    # backfill to now() rather than leave a NOT NULL column with nulls in
    # it, which alter_column(nullable=False) below would otherwise reject.
    bind = op.get_bind()
    bind.execute(sa.text(f'UPDATE "{schema}".correlation_rule_states SET last_triggered_at = now() WHERE last_triggered_at IS NULL'))
    op.alter_column(
        "correlation_rule_states",
        "last_triggered_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema=schema,
    )
    op.drop_column("correlation_rule_states", "ml_event_count", schema=schema)
    op.drop_column("correlation_rule_states", "ml_model", schema=schema)
    op.drop_column("correlation_rules", "ml_warmup_count", schema=schema)
    op.drop_column("correlation_rules", "ml_score_threshold", schema=schema)
