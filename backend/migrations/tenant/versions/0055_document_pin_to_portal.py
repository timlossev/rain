"""documents.pin_to_portal: opt-in, per-document flag that highlights
that document's contents (same rendered-Markdown/plain-text preview as
rain.modules.home's own "Show on landing page", migration 0045) between
"Today's events" and the main form on the public client portal
(rain.modules.portal) -- the Trust Center's own equivalent of pinning a
document to the internal landing page, but never coupled to it: a
tenant can pin a different document (or none) to each.

Deliberately independent of is_shareable: pin_to_portal alone does NOT
make a document public. rain.modules.documents.service.
get_portal_pinned_document only ever returns a document that is BOTH
pinned AND is_shareable, so flipping this flag on a non-shareable
document has no visible effect until that document is also marked
shareable -- the portal can never leak a non-public document just
because an admin pinned it. Off by default, same opt-in posture as
is_shareable/show_on_landing_page.

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0054.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "documents",
        sa.Column("pin_to_portal", sa.Boolean(), nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "pin_to_portal", schema=schema)
