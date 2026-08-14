"""tickets.start_date/end_date: DATE -> TIMESTAMPTZ, so a change
ticket's window can carry a time-of-day, not just a day (the New Ticket
form now uses <input type="datetime-local">). Existing values keep
midnight UTC as their time component.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.alter_column() doesn't respect this env.py's schema_translate_map
    # either -- see the NOTE in script.py.mako, hit for real by 0005/0006/
    # 0013/0015/0016/0017/0018.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.alter_column(
        "tickets",
        "start_date",
        existing_type=sa.Date,
        type_=sa.DateTime(timezone=True),
        postgresql_using="start_date::timestamptz",
        schema=schema,
    )
    op.alter_column(
        "tickets",
        "end_date",
        existing_type=sa.Date,
        type_=sa.DateTime(timezone=True),
        postgresql_using="end_date::timestamptz",
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.alter_column("tickets", "start_date", existing_type=sa.DateTime(timezone=True), type_=sa.Date, schema=schema)
    op.alter_column("tickets", "end_date", existing_type=sa.DateTime(timezone=True), type_=sa.Date, schema=schema)
