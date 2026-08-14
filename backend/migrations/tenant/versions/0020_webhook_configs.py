"""webhook_configs: centrally-configured outbound webhooks, referenced
by id from Platform Response Rules' "webhook" action (previously an
inline url/payload_template on the action itself) and from a new
Document "populate from webhook" setting. documents gains webhook_id/
alert_on_change/last_refreshed_at for that second use.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.create_table()/op.add_column() don't respect this env.py's
    # schema_translate_map -- see the NOTE in script.py.mako, hit for
    # real by 0005/0006/0013/0015/0016/0017/0018/0019.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("http_method", sa.String(10), nullable=False, server_default="POST"),
        sa.Column("headers", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("payload_template", sa.Text, nullable=False, server_default="{}"),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="10"),
        sa.Column("success_codes", sa.String(255), nullable=False, server_default="200,201,202,204"),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=schema,
    )
    op.add_column(
        "documents",
        sa.Column("webhook_id", sa.Integer, sa.ForeignKey(f"{schema}.webhook_configs.id", ondelete="SET NULL"), nullable=True),
        schema=schema,
    )
    op.add_column(
        "documents", sa.Column("alert_on_change", sa.Boolean, nullable=False, server_default="false"), schema=schema
    )
    op.add_column(
        "documents", sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True), schema=schema
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "last_refreshed_at", schema=schema)
    op.drop_column("documents", "alert_on_change", schema=schema)
    op.drop_column("documents", "webhook_id", schema=schema)
    op.drop_table("webhook_configs", schema=schema)
