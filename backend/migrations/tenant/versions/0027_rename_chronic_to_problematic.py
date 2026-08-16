"""tickets.is_chronic -> tickets.is_problematic. Same manually-set
"recurring issue" flag from 0016, renamed end to end (column, model
field, route, form field, TicketFieldChange.field_name value, UI text)
-- "problematic" reads better next to "chronic" being an unusual word
choice for a ticket, not a medical condition.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.alter_column() needs schema= passed explicitly to respect this
    # env.py's schema_translate_map -- see the NOTE in script.py.mako,
    # hit for real by 0005/.../0026.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.alter_column(
        "tickets",
        "is_chronic",
        new_column_name="is_problematic",
        existing_type=sa.Boolean,
        existing_server_default="false",
        schema=schema,
    )
    # TicketFieldChange.field_name is a free-text column (not an FK), so
    # existing activity-feed rows recorded against the old field name
    # need updating too, or the ticket detail page's per-field_name
    # branch (now checking "is_problematic") would stop recognizing them
    # and they'd silently fall out of the rendered activity feed.
    bind = op.get_bind()
    bind.execute(
        sa.text(f'UPDATE "{schema}".ticket_field_changes SET field_name = \'is_problematic\' WHERE field_name = \'is_chronic\'')
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    bind = op.get_bind()
    bind.execute(
        sa.text(f'UPDATE "{schema}".ticket_field_changes SET field_name = \'is_chronic\' WHERE field_name = \'is_problematic\'')
    )
    op.alter_column(
        "tickets",
        "is_problematic",
        new_column_name="is_chronic",
        existing_type=sa.Boolean,
        existing_server_default="false",
        schema=schema,
    )
