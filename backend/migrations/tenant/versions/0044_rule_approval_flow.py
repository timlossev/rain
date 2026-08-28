"""ticket_rules.approval_flow_id: which ApprovalFlow a rule-produced
change ticket attaches automatically, instead of always filing an
unprotected one. Only meaningful for a rule whose ticket_type is
"change" -- ignored otherwise, same as asset_match_field/group_by/etc.
already are for the promotion_type/ticket_type combinations they don't
apply to.

A change ticket a rule produces (rain.modules.tickets.rules.apply_rule/
_fire_ml, whichever promotion_type fired it) also defaults its
implementation window to "starts now, 24h turnaround" -- start_date/
end_date on the Ticket itself, no schema change needed for that part,
just new logic in rules.py.

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0043.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "ticket_rules",
        sa.Column(
            "approval_flow_id", sa.Integer, sa.ForeignKey("approval_flows.id", ondelete="SET NULL"), nullable=True
        ),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("ticket_rules", "approval_flow_id", schema=schema)
