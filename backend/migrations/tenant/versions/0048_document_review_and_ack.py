"""documents.next_review_at: an optional, admin-set date after which a
document is flagged "overdue for review" on the Documents list (the
overdue-only filter and its flag icon both key off this) -- a plain date,
not tied to the existing CalendarEntry.document_id/recurrence machinery,
since a policy owner may want a review deadline tracked without also
wanting a recurring reminder set up for it. Independent of owner_user_id
(0047) -- who's accountable for the document, and when it's next due for
review, are two separate facts.

document_acknowledgments: one row per (document, user) who has clicked
"I have read this" on the document's own page, upserted (ON CONFLICT ...
DO UPDATE) rather than accumulating a new row per click, so
acknowledged_at always reflects the most recent read rather than the
first one. ON DELETE CASCADE on document_id, same reasoning as
DocumentLink -- an acknowledgment of a deleted document has no reason to
survive as an orphan. user_id is the same unenforced cross-schema
control.users id every other per-user reference in this schema already
uses (owner_user_id, uploaded_by, ...).

Together these two additions are what a policy-review and staff-
attestation trail looks like in this schema -- see docs/
eucs-compliance-assessment.md and docs/itsm-controls-mapping.md for which
controls (periodic policy review, security-awareness acknowledgment) that
evidence actually satisfies.

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0047.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column("documents", sa.Column("next_review_at", sa.Date(), nullable=True), schema=schema)

    op.create_table(
        "document_acknowledgments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        # control.users id -- cross-schema, plain integer per this project's
        # documented schema-per-tenant trade-off (see tenant_models.py docstring).
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "user_id", name="uq_document_acknowledgments_doc_user"),
    )
    op.create_index("ix_document_acknowledgments_document_id", "document_acknowledgments", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_acknowledgments")
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "next_review_at", schema=schema)
