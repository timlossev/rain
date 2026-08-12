"""syslog source -> tenant routing table

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.create_table(
        "syslog_source_map",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_field", sa.String(15), nullable=False),
        sa.Column("pattern", sa.String(255), nullable=False),
        sa.Column("is_regex", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_control_syslog_source_map_tenant", "syslog_source_map", ["tenant_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("syslog_source_map", schema=SCHEMA)
