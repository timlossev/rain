"""documents.refresh_on_view: opt-in, per-document flag that calls the
document's configured webhook (webhook_id, migration 0037) every time its
detail page is rendered, not just on the manual "Refresh from webhook"
button (rain.modules.documents.service.refresh_from_webhook) -- same
underlying call/diff/save logic either way, so a success overwrites the
stored copy before the page renders it and a failure leaves the
previously-stored copy untouched (refresh_from_webhook already never
writes on failure; this only decides *when* it gets called). Off by
default, and only meaningful once a webhook is actually configured --
same "starts locked down, needs its prerequisite set up first" posture
show_on_landing_page (0045) and is_shareable (0042) both already have.

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0045.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "documents",
        sa.Column("refresh_on_view", sa.Boolean(), nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "refresh_on_view", schema=schema)
