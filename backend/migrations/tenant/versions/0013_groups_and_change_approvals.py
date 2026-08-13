"""Groups (tenant-scoped user groups) + approval flows/steps (templates) +
change_approvals/change_approval_decisions (per-ticket instances) +
tickets.start_date/end_date/source_ticket_id for the new "change" ticket
type -- promotable from an incident/vulnerability, with its own start/end
window (shown on the calendar) and an ordered, group-or-user approval
lifecycle.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "group_memberships",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        # control.users id -- cross-schema, plain integer per this project's
        # documented schema-per-tenant trade-off (see tenant_models.py docstring).
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_memberships_group_user"),
    )
    op.create_index("ix_group_memberships_group_id", "group_memberships", ["group_id"])

    op.create_table(
        "approval_flows",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "approval_flow_steps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flow_id", sa.Integer, sa.ForeignKey("approval_flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("approver_group_id", sa.Integer, sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True),
        # control.users id, cross-schema plain integer -- same trade-off as above.
        sa.Column("approver_user_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_approval_flow_steps_flow_id", "approval_flow_steps", ["flow_id"])

    # op.add_column() does NOT respect this env.py's schema_translate_map
    # (see the NOTE in script.py.mako, confirmed the hard way by migrations
    # 0005/0006 before this one) -- schema= must be passed explicitly.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column("tickets", sa.Column("start_date", sa.Date, nullable=True), schema=schema)
    op.add_column("tickets", sa.Column("end_date", sa.Date, nullable=True), schema=schema)
    op.add_column(
        "tickets",
        sa.Column("source_ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True),
        schema=schema,
    )

    op.create_table(
        "change_approvals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("flow_id", sa.Integer, sa.ForeignKey("approval_flows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("current_step_order", sa.Integer, nullable=False, server_default="0"),
        # pending | approved | rejected
        sa.Column("overall_status", sa.String(15), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "change_approval_decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "approval_id", sa.Integer, sa.ForeignKey("change_approvals.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("step_order", sa.Integer, nullable=False),
        # Snapshot of the step's label at decision time -- survives later
        # edits to the flow template without rewriting history.
        sa.Column("step_label", sa.String(255), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer, nullable=False),
        # approved | rejected
        sa.Column("decision", sa.String(15), nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_change_approval_decisions_approval_id", "change_approval_decisions", ["approval_id"])


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_table("change_approval_decisions")
    op.drop_table("change_approvals")
    op.drop_column("tickets", "source_ticket_id", schema=schema)
    op.drop_column("tickets", "end_date", schema=schema)
    op.drop_column("tickets", "start_date", schema=schema)
    op.drop_table("approval_flow_steps")
    op.drop_table("approval_flows")
    op.drop_table("group_memberships")
    op.drop_table("groups")
