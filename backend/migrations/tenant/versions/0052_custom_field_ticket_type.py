"""custom_fields.ticket_type: asset_type_id's ticket-scoped counterpart --
only ever set on a scope="ticket" row, NULL meaning "every ticket type"
(the only behavior before this column existed, so every pre-existing row
keeps its current behavior unchanged on upgrade). One of "incident"/
"vulnerability"/"change" scopes a ticket-scoped field to just that type
instead of rendering (unfilled) on all three -- see rain.modules.tickets.
service.ticket_fields' own docstring for the filtering this enables, and
CustomField's for why this needed asking about before it existed: FedRAMP
SCN fields showing up empty on every incident and vulnerability, not just
the Change tickets they're meant for.

uq_custom_fields_scope_type_key is dropped and recreated to include the
new column -- Postgres treats NULL as distinct from NULL in a unique
constraint, so this doesn't retroactively enforce anything new against
existing rows (all NULL today), it just makes room for a future field_key
to be reused once for "change" and once for "incident" as two genuinely
different fields, the same way asset_type_id already lets one field_key
repeat across different asset types.

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.create_unique_constraint()/op.drop_constraint()
    # need schema= passed explicitly -- see the NOTE in script.py.mako,
    # hit for real by 0005/.../0050.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column("custom_fields", sa.Column("ticket_type", sa.String(15), nullable=True), schema=schema)
    op.drop_constraint("uq_custom_fields_scope_type_key", "custom_fields", schema=schema, type_="unique")
    op.create_unique_constraint(
        "uq_custom_fields_scope_type_key",
        "custom_fields",
        ["scope", "asset_type_id", "ticket_type", "field_key"],
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_constraint("uq_custom_fields_scope_type_key", "custom_fields", schema=schema, type_="unique")
    op.create_unique_constraint(
        "uq_custom_fields_scope_type_key", "custom_fields", ["scope", "asset_type_id", "field_key"], schema=schema
    )
    op.drop_column("custom_fields", "ticket_type", schema=schema)
