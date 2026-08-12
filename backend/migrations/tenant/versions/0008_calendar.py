"""calendar_entries: per-tenant calendar with recurring-entry presets and
a bridge to synthesize syslog events (so Event Policy rules can react)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("recurrence", sa.String(15), nullable=True),
        sa.Column("recurrence_end", sa.Date, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("emit_syslog_event", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("event_program", sa.String(255), nullable=True),
        sa.Column("policy_ref", postgresql.JSONB, nullable=True),
        sa.Column("last_fired_date", sa.Date, nullable=True),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_calendar_entries_start_date", "calendar_entries", ["start_date"])


def downgrade() -> None:
    op.drop_table("calendar_entries")
