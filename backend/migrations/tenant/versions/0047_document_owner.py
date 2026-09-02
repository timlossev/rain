"""documents.owner_user_id: who's responsible for keeping this document
current -- a plain, cross-schema control.users id (same "unenforced FK,
validated at the app layer" trade-off as Ticket.assignee_user_id, see
tenant_models' own module docstring on cross-schema references), separate
from uploaded_by (a one-time fact about who created the document, never
reassigned) and independent of webhook_id/refresh_on_view (an owner is a
person accountable for a document's accuracy whether or not it happens to
auto-refresh from anywhere). Backs the Documents Kanban board's "group by
owner" workload view (rain.modules.documents.router.documents_kanban),
the same role Ticket.assignee_user_id plays for the tickets board.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0046.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column("documents", sa.Column("owner_user_id", sa.Integer(), nullable=True), schema=schema)


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "owner_user_id", schema=schema)
