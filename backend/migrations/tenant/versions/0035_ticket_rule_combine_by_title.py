"""ticket_rules.combine_by_title: opt-in, per-policy checkbox -- when a
matching event's computed title equals an already-open ticket of the same
type, fold the event into that ticket (a comment noting the repeat
occurrence + is_problematic turned on) instead of creating a new one. See
rain.modules.tickets.service.find_open_ticket_by_title /
combine_event_into_ticket and rules.apply_rule.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "ticket_rules",
        sa.Column("combine_by_title", sa.Boolean, nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("ticket_rules", "combine_by_title", schema=schema)
