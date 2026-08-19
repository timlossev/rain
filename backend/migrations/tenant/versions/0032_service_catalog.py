"""service_catalog_items + service_catalog_fields (rain.modules.catalog):
a tenant-defined self-service catalog, each item an up-to-10-question form
that produces a ticket on submission, optionally routed through an
existing ApprovalFlow. Also adds tickets.source_catalog_item_id so a
ticket produced this way can be traced back to the catalog entry that
created it (SET NULL, not a hard dependency).

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_catalog_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.String(63), nullable=True),
        sa.Column("ticket_type", sa.String(15), nullable=False, server_default="incident"),
        sa.Column("default_severity", sa.String(15), nullable=False, server_default="medium"),
        sa.Column("payload_format", sa.String(7), nullable=False, server_default="json"),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("approval_flow_id", sa.Integer, sa.ForeignKey("approval_flows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("key", name="uq_service_catalog_items_key"),
    )

    op.create_table(
        "service_catalog_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "catalog_item_id", sa.Integer, sa.ForeignKey("service_catalog_items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("field_key", sa.String(63), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("field_type", sa.String(15), nullable=False, server_default="text"),
        sa.Column("select_options", postgresql.JSONB, nullable=True),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_mode", sa.String(15), nullable=True),
        sa.Column("source_expression", sa.Text, nullable=True),
        sa.UniqueConstraint("catalog_item_id", "field_key", name="uq_service_catalog_fields_item_key"),
    )
    op.create_index("ix_service_catalog_fields_catalog_item_id", "service_catalog_fields", ["catalog_item_id"])

    # op.add_column() needs schema= passed explicitly to respect this
    # env.py's schema_translate_map -- see the NOTE in script.py.mako,
    # hit for real by 0005/.../0031. op.create_table() above doesn't need
    # it (same established split as every prior migration that does both).
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "tickets",
        sa.Column(
            "source_catalog_item_id",
            sa.Integer,
            sa.ForeignKey("service_catalog_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("tickets", "source_catalog_item_id", schema=schema)
    op.drop_table("service_catalog_fields")
    op.drop_table("service_catalog_items")
