"""ticket_rules.ml_algorithm: which river.anomaly detector an ml_anomaly
promotion policy uses -- was hardcoded to HalfSpaceTrees; now selectable
per policy (rain.modules.tickets.rules.ML_ALGORITHMS), a genuine choice
between three algorithms that share the same score_one(x)/learn_one(x)
shape (confirmed against the installed river==0.21.2: the other three
anomaly detectors in that version -- GaussianScorer, StandardAbsolute
Deviation, PredictiveAnomalyDetection -- need a supervised target `y`
this app has no ground truth for, so they aren't real options here).

ticket_rule_states.ml_feature_stats: running per-feature mean/variance
(Welford's online algorithm, plain JSON -- {"severity": {"n":, "mean":,
"m2":}, ...}), kept alongside the pickled model so a firing event can be
explained ("flagged mainly because message length (312) is well above
this source's typical ~48") instead of just a bare anomaly score. Plain
JSON rather than pickling river.stats objects into the same blob: one
fewer moving part, and directly inspectable if ever queried by hand.

ix_syslog_events_promoted_ticket_id: the "chronic ticket log summary"
feature (rain.modules.tickets.rootcause) queries every SyslogEvent tied
to a ticket via promoted_ticket_id -- a real query pattern now, not
previously indexed.

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.create_index() need schema= passed explicitly --
    # see the NOTE in script.py.mako, hit for real by 0005/.../0040.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "ticket_rules",
        sa.Column("ml_algorithm", sa.String(20), nullable=False, server_default="half_space_trees"),
        schema=schema,
    )
    op.add_column(
        "ticket_rule_states", sa.Column("ml_feature_stats", postgresql.JSONB, nullable=True), schema=schema
    )
    op.create_index(
        "ix_syslog_events_promoted_ticket_id", "syslog_events", ["promoted_ticket_id"], schema=schema
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_index("ix_syslog_events_promoted_ticket_id", table_name="syslog_events", schema=schema)
    op.drop_column("ticket_rule_states", "ml_feature_stats", schema=schema)
    op.drop_column("ticket_rules", "ml_algorithm", schema=schema)
