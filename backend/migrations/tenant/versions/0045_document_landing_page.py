"""documents.show_on_landing_page: opt-in, per-document flag that shows
that document's contents (rendered Markdown, or plain text for a
non-Markdown text file) on the new landing page (rain.modules.home) --
the same "starts locked down, admin opts in" posture is_shareable
(migration 0042) already established for surfacing a document outside
its own detail page. Off by default; a document with no inline body at
all (an uploaded binary file, e.g. a PDF) can still have this set --
rain.modules.home.router just skips it if there's nothing to render,
same as its own body_kind() check does everywhere else a document's
body is read.

More than one document can be flagged at once -- the landing page
renders every flagged one (ordered by title), falling back to a plain
"Welcome to <instance>" only when none are.

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0044.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "documents",
        sa.Column("show_on_landing_page", sa.Boolean(), nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "show_on_landing_page", schema=schema)
