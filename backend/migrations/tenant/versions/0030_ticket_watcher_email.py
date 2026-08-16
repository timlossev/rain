"""ticket_watchers: user_id becomes nullable, a new email column lets a
watcher be a bare email address instead of a system user (e.g. someone
added via a Platform Response Rule's "Add a watcher" action) -- exactly
one of the two is ever set. A partial, case-insensitive unique index on
(ticket_id, lower(email)) mirrors the existing (ticket_id, user_id)
UniqueConstraint for the user_id case.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.alter_column()/op.add_column() need schema= passed explicitly to
    # respect this env.py's schema_translate_map -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0029.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.alter_column(
        "ticket_watchers",
        "user_id",
        existing_type=sa.Integer,
        nullable=True,
        schema=schema,
    )
    op.add_column(
        "ticket_watchers",
        sa.Column("email", sa.String(320), nullable=True),
        schema=schema,
    )
    op.execute(
        f'CREATE UNIQUE INDEX uq_ticket_watchers_ticket_email ON "{schema}".ticket_watchers '
        f"(ticket_id, lower(email)) WHERE email IS NOT NULL"
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.execute(f'DROP INDEX IF EXISTS "{schema}".uq_ticket_watchers_ticket_email')
    op.drop_column("ticket_watchers", "email", schema=schema)
    # A null user_id (only possible from an email-only watcher row, which
    # downgrade doesn't attempt to preserve) has no sane "system user"
    # equivalent -- delete those rows rather than leave a NOT NULL column
    # with nulls in it, which alter_column(nullable=False) below would
    # otherwise reject.
    bind = op.get_bind()
    bind.execute(sa.text(f'DELETE FROM "{schema}".ticket_watchers WHERE user_id IS NULL'))
    op.alter_column(
        "ticket_watchers",
        "user_id",
        existing_type=sa.Integer,
        nullable=False,
        schema=schema,
    )
