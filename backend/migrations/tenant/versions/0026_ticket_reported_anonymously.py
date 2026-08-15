"""tickets.reported_anonymously: distinguishes a ticket filed through the
public incident portal (rain.modules.portal) with no session at all from
one that simply has no reporter_user_id for some other reason (a
promoted/correlated event, an import, ...) -- see
rain.modules.tickets.service.create_ticket and the "Reported by" line on
the ticket detail page and PDF export.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly to respect this
    # env.py's schema_translate_map -- see the NOTE in script.py.mako,
    # hit for real by 0005/.../0025.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "tickets",
        sa.Column("reported_anonymously", sa.Boolean, nullable=False, server_default=sa.text("false")),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("tickets", "reported_anonymously", schema=schema)
