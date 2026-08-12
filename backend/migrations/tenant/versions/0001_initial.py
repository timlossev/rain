"""initial tenant schema -- asset registry (Milestone 1)

Revision ID: 0001
Revises:
Create Date: 2026-08-12

Applied once per tenant into `tenant_<slug>`, via schema_translate_map
(see migrations/tenant/env.py) -- no table here declares an explicit
schema, that's what makes this file reusable across tenants.

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_types",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("icon", sa.String(63), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("key", name="uq_asset_types_key"),
    )

    op.create_table(
        "custom_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_type_id", sa.Integer, sa.ForeignKey("asset_types.id", ondelete="CASCADE"), nullable=True),
        sa.Column("field_key", sa.String(63), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("field_type", sa.String(15), nullable=False, server_default="text"),
        sa.Column("select_options", postgresql.JSONB, nullable=True),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("asset_type_id", "field_key", name="uq_custom_fields_type_key"),
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_type_id", sa.Integer, sa.ForeignKey("asset_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(63), nullable=False, server_default="active"),
        sa.Column("owner_user_id", sa.Integer, nullable=True),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("updated_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("external_id", name="uq_assets_external_id"),
    )
    op.create_index("ix_assets_asset_type_id", "assets", ["asset_type_id"])

    op.create_table(
        "asset_field_values",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", sa.Integer, sa.ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", "field_id", name="uq_asset_field_values"),
    )
    op.create_index("ix_asset_field_values_asset_id", "asset_field_values", ["asset_id"])

    op.create_table(
        "export_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("asset_type_id", sa.Integer, sa.ForeignKey("asset_types.id", ondelete="CASCADE"), nullable=True),
        sa.Column("format", sa.String(15), nullable=False, server_default="csv"),
        sa.Column("columns", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sync_connections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(15), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "sync_connection_id", sa.Integer, sa.ForeignKey("sync_connections.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(31), nullable=False, server_default="pending"),
        sa.Column("summary", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error_text", sa.Text, nullable=True),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_user_id", sa.Integer, nullable=True),
        sa.Column("action", sa.String(127), nullable=False),
        sa.Column("entity_type", sa.String(127), nullable=False),
        sa.Column("entity_id", sa.String(127), nullable=True),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("sync_runs")
    op.drop_table("sync_connections")
    op.drop_table("export_profiles")
    op.drop_table("asset_field_values")
    op.drop_table("assets")
    op.drop_table("custom_fields")
    op.drop_table("asset_types")
