"""Drop the cloud-sync scaffolding (sync_connections, sync_runs) --
AWS/Azure discovery never got past a NotImplementedError stub, and the
webhook-driven document population added in 0020/0021 (call a webhook,
diff the result, alert on change) supersedes the whole concept for the
"keep this in sync with an external source" use case.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.drop_table() doesn't respect this env.py's schema_translate_map --
    # see the NOTE in script.py.mako, hit for real by 0005/.../0021.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_table("sync_runs", schema=schema)
    op.drop_table("sync_connections", schema=schema)


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.create_table(
        "sync_connections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(15), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=schema,
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "sync_connection_id",
            sa.Integer,
            sa.ForeignKey(f"{schema}.sync_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(31), nullable=False, server_default="pending"),
        sa.Column("summary", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error_text", sa.Text, nullable=True),
        schema=schema,
    )
