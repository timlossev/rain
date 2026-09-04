"""tickets.external_finding_key: an optional, deterministic identity for
a ticket that originated from an external system's own recurring
export (a vulnerability scanner's CSV/JSON, today; any future source
that has its own stable per-finding identity could reuse the same
column) -- what makes deduplication across repeated imports possible at
all. NULL for every ticket created any other way (manual form, syslog
promotion, Service Catalog, an import that never mapped a "Dedup key"
column) -- a plain UniqueConstraint on a nullable column is exactly
right here, since Postgres allows unlimited NULLs under one and this
column is only ever meaningful for the minority of tickets that came in
through that one import path.

Deliberately not scoped to Nessus specifically, in naming or shape --
see rain.modules.tickets.importer's own module docstring for the
mapping-target ("upsert_key") that populates it and the three-way
create/leave-alone/reopen logic keyed off it.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.create_unique_constraint() need schema= passed
    # explicitly -- see the NOTE in script.py.mako, hit for real by
    # 0005/.../0049.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column("tickets", sa.Column("external_finding_key", sa.String(255), nullable=True), schema=schema)
    op.create_unique_constraint("uq_tickets_external_finding_key", "tickets", ["external_finding_key"], schema=schema)


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_constraint("uq_tickets_external_finding_key", "tickets", schema=schema, type_="unique")
    op.drop_column("tickets", "external_finding_key", schema=schema)
