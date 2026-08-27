"""ticket_rules.ml_sidecar_enabled: lets a "repetition" policy also run
anomaly detection on the same events it's folding, instead of needing a
second, separate "ml_anomaly" policy with a duplicated pattern just to
get an anomaly signal on the same population.

"repetition" and "ml_anomaly" were two of three mutually-exclusive
promotion_type tabs, as if consolidating repeats and flagging anomalies
were competing concerns -- they aren't: repetition decides whether an
event folds into an already-open ticket or starts a new one (a
deterministic, immediate rule), while ML anomaly detection is an
orthogonal statistical layer that can just as well watch the population
a repetition rule is already tracking. Rather than force every
repetition rule to also carry the full ML anomaly settings (algorithm,
threshold, warm-up, cooldown, group by), this is a single opt-in
checkbox, on by default for a newly created repetition rule (default
set client-side by rain.modules.tickets.router's Form default, not this
column's own server_default, which stays False so no *existing*
repetition rule silently starts scoring events it was never configured
to) -- reusing whatever this row's own ml_algorithm/group_by/
window_minutes/ml_score_threshold/ml_warmup_count columns already hold
(the same "recommended standard configuration" every rule already gets
via those columns' own server_defaults, since the create/edit forms
always submit all five regardless of which promotion-type tab is
active). A fired anomaly is added as a comment on whichever ticket
repetition already touched (new or folded-into), never a second,
separate ticket -- see rain.modules.tickets.rules._annotate_if_anomalous.

Revision ID: 0043
Revises: 0042
Create Date: 2026-08-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0042.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "ticket_rules",
        sa.Column("ml_sidecar_enabled", sa.Boolean(), nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("ticket_rules", "ml_sidecar_enabled", schema=schema)
