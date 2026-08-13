"""tickets.is_chronic: manually-set flag for a ticket that's a recurring
problem (conventionally, one that's happened more than 5 times in the
trailing 30 days) rather than a one-off -- surfaced as an icon next to
the title and toggleable from the tickets list quick-action menu.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() doesn't respect this env.py's schema_translate_map --
    # see the NOTE in script.py.mako, hit for real by 0005/0006/0013/0015.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "tickets", sa.Column("is_chronic", sa.Boolean, nullable=False, server_default="false"), schema=schema
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("tickets", "is_chronic", schema=schema)
