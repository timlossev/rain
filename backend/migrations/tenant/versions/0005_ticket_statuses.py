"""per-tenant customizable ticket statuses, seeded with the previous
hardcoded set (open/in_progress/resolved/closed) so existing tickets'
status values keep resolving to something

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULTS = [
    {"key": "open", "label": "Open", "color": "#2563eb", "is_closed": False, "is_active": True, "sort_order": 0},
    {"key": "in_progress", "label": "In Progress", "color": "#d97706", "is_closed": False, "is_active": True, "sort_order": 1},
    {"key": "resolved", "label": "Resolved", "color": "#0d9488", "is_closed": False, "is_active": True, "sort_order": 2},
    {"key": "closed", "label": "Closed", "color": "#6b7280", "is_closed": True, "is_active": True, "sort_order": 3},
]


def upgrade() -> None:
    op.create_table(
        "ticket_statuses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(31), nullable=False),
        sa.Column("label", sa.String(63), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#6b7280"),
        sa.Column("is_closed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("key", name="uq_ticket_statuses_key"),
    )
    # Neither op.bulk_insert() nor op.execute(sa.insert(sa.table(...))) picked
    # up this connection's schema_translate_map -- confirmed via two separate
    # real runs, both landed on unqualified "ticket_statuses" with no schema
    # prefix in the emitted SQL and failed with UndefinedTableError. Reading
    # the target schema directly off the same execution_options env.py set
    # on this connection (see migrations/tenant/env.py's do_run_migrations)
    # and fully-qualifying the raw SQL ourselves sidesteps the question of
    # *why* those two didn't translate -- there's no translation left to do.
    bind = op.get_bind()
    schema = bind.get_execution_options()["schema_translate_map"][None]
    insert_sql = sa.text(
        f'INSERT INTO "{schema}".ticket_statuses (key, label, color, is_closed, is_active, sort_order) '
        "VALUES (:key, :label, :color, :is_closed, :is_active, :sort_order)"
    )
    for row in _DEFAULTS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    op.drop_table("ticket_statuses")
