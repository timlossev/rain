"""export_profiles.scope: distinguishes an asset export profile from a
ticket one now that tickets/export.html gained the same save/load
profile feature assets/export.html already had -- both share this one
table (asset_type_id stays null for a ticket-scoped row) rather than
duplicating the whole concept. Existing rows are all asset profiles
(the only kind that existed before this), hence the "asset" default.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() doesn't respect this env.py's schema_translate_map --
    # see the NOTE in script.py.mako, hit for real by 0005/0006/0013/0015/
    # 0016/0017.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "export_profiles", sa.Column("scope", sa.String(10), nullable=False, server_default="asset"), schema=schema
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("export_profiles", "scope", schema=schema)
