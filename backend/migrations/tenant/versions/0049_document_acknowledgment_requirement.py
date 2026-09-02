"""documents.ack_required_group_id / ack_required_user_id / ack_requested_at:
an optional "this document requires acknowledgment from X" assignment,
the same group-or-user shape ApprovalFlowStep already uses for a change
ticket's approvers (exactly one of the two set, enforced at the app
layer -- see rain.modules.documents.service.request_acknowledgment).
ack_requested_at is when the current requirement was (re)issued -- NULL
means "no requirement set at all," not just "nobody's acknowledged yet";
re-requesting (bumping it to now) is what makes a document pending again
for someone who already acknowledged an earlier version, without
touching their old DocumentAcknowledgment row.

platform_event_triggers.ticket_id becomes nullable, and gains a sibling
document_id -- Platform Response Rules' trigger/action/log engine
(rain.modules.tickets.platform_events) now also reacts to a document
entering "pending acknowledgment" (trigger_event=
"document_pending_acknowledgment"), not just ticket lifecycle events, so
its own audit-trail table needs to point at either kind of record.
Exactly one of the two is set per row, same unenforced-at-the-DB
convention as everywhere else in this schema that makes that trade-off.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.alter_column() need schema= passed explicitly --
    # see the NOTE in script.py.mako, hit for real by 0005/.../0048.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "documents",
        sa.Column("ack_required_group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True),
        schema=schema,
    )
    op.add_column("documents", sa.Column("ack_required_user_id", sa.Integer(), nullable=True), schema=schema)
    op.add_column("documents", sa.Column("ack_requested_at", sa.DateTime(timezone=True), nullable=True), schema=schema)

    op.alter_column("platform_event_triggers", "ticket_id", existing_type=sa.Integer(), nullable=True, schema=schema)
    op.add_column(
        "platform_event_triggers",
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        schema=schema,
    )
    op.create_index("ix_platform_event_triggers_document_id", "platform_event_triggers", ["document_id"], schema=schema)


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_index("ix_platform_event_triggers_document_id", table_name="platform_event_triggers", schema=schema)
    op.drop_column("platform_event_triggers", "document_id", schema=schema)
    op.alter_column("platform_event_triggers", "ticket_id", existing_type=sa.Integer(), nullable=False, schema=schema)
    op.drop_column("documents", "ack_requested_at", schema=schema)
    op.drop_column("documents", "ack_required_user_id", schema=schema)
    op.drop_column("documents", "ack_required_group_id", schema=schema)
