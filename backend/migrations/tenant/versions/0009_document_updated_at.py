"""documents.updated_at -- documents became editable in-place (inline
txt/md body editor), so "last edited" needs tracking; previously
immutable-after-upload, so this didn't exist

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # add_column() needs schema= explicitly -- see migrations/tenant/
    # script.py.mako's header note (op.add_column doesn't pick up this
    # connection's schema_translate_map on its own).
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "documents",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "updated_at", schema=schema)
