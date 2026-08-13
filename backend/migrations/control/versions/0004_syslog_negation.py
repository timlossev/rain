"""syslog_source_map gains an `action` ("route" | "discard") so a source
rule can drop matching events entirely instead of only ever routing them
to a tenant -- backs the /tickets/live "Discard these" bulk action and
the corresponding negation-rule section of Admin > Syslog Sources.
tenant_id becomes nullable since a discard rule has no tenant.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.add_column(
        "syslog_source_map",
        sa.Column("action", sa.String(10), nullable=False, server_default="route"),
        schema=SCHEMA,
    )
    op.alter_column("syslog_source_map", "tenant_id", existing_type=sa.Integer, nullable=True, schema=SCHEMA)


def downgrade() -> None:
    op.alter_column("syslog_source_map", "tenant_id", existing_type=sa.Integer, nullable=False, schema=SCHEMA)
    op.drop_column("syslog_source_map", "action", schema=SCHEMA)
