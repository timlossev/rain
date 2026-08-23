"""custom_fields.scope + ticket_field_values: custom attributes on
tickets, same shape as assets' -- scope ("asset" | "ticket") distinguishes
the two kinds of CustomField row now sharing this one definitions table
(same reasoning as 0018's export_profiles.scope: one table beats
duplicating the whole concept). asset_type_id stays null for every
ticket-scoped row -- tickets don't have per-tenant *types* the way assets
do (ticket_type is a fixed 3-value enum, not user-defined), so a
ticket-scoped custom field always applies tenant-wide across all three
types rather than being scoped to one of them, matching how tickets
already share one record/activity-feed/export-pipeline regardless of
type. Existing rows are all asset fields (the only kind before this),
hence the "asset" default.

The old (asset_type_id, field_key) unique constraint would have silently
allowed a same-keyed asset-scoped and ticket-scoped field to collide (two
tenant-wide rows both carrying asset_type_id=NULL) -- widened to include
scope.

ticket_field_values mirrors asset_field_values exactly, just against
tickets instead of assets; no is_required support for a ticket-scoped
field (see rain.modules.tickets.schemas' own note) since a ticket can be
created by several automated paths (Event Promotion Policies, the public
portal, Service Catalog submissions) that don't know about custom fields
at all -- a required one would silently break those instead of just
being asked for on the manual creation form.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.drop_constraint()/op.create_unique_constraint()
    # need schema= passed explicitly to respect this env.py's
    # schema_translate_map -- see the NOTE in script.py.mako, hit for real
    # by 0005/.../0036. op.create_table() (for a table this same migration
    # creates) doesn't need it -- same established split 0032 already
    # relies on.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "custom_fields", sa.Column("scope", sa.String(10), nullable=False, server_default="asset"), schema=schema
    )
    op.drop_constraint("uq_custom_fields_type_key", "custom_fields", type_="unique", schema=schema)
    op.create_unique_constraint(
        "uq_custom_fields_scope_type_key", "custom_fields", ["scope", "asset_type_id", "field_key"], schema=schema
    )

    op.create_table(
        "ticket_field_values",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", sa.Integer, sa.ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticket_id", "field_id", name="uq_ticket_field_values"),
    )
    op.create_index("ix_ticket_field_values_ticket_id", "ticket_field_values", ["ticket_id"])


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.drop_index("ix_ticket_field_values_ticket_id", table_name="ticket_field_values")
    op.drop_table("ticket_field_values")

    op.drop_constraint("uq_custom_fields_scope_type_key", "custom_fields", type_="unique", schema=schema)
    op.create_unique_constraint(
        "uq_custom_fields_type_key", "custom_fields", ["asset_type_id", "field_key"], schema=schema
    )
    op.drop_column("custom_fields", "scope", schema=schema)
