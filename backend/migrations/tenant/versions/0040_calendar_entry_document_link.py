"""calendar_entries.document_id: a plain, optional link from a calendar
entry to a document -- "this reminder is about document X" -- independent
of policy_ref's existing "refresh_document" auto-update mechanism (0010).
Before this, the only way a calendar entry referenced a document was
buried inside policy_ref's JSON, and only for entries that also auto-
refreshed that document's content from a webhook on every occurrence --
there was no way to just tie a plain reminder to a document (e.g. "this
document is due for revision every quarter") without also wiring up
auto-update. document_id is that plain link: it's what backs a document's
own new Calendar tab (rain.modules.documents.router.document_detail) and
what the calendar entry form's "Related document" picker sets, and it's
ON DELETE CASCADE (a revision reminder for a deleted document has no
reason to survive as an orphan) -- same choice DocumentLink.document_id
already made for the same reason.

Backfills document_id from any existing policy_ref.document_id (refresh_
document rows only -- that's the only shape policy_ref has ever had) so
those entries immediately show up in the referenced document's own
Calendar tab too, and the entry form's now-unified document picker
reflects what they already do rather than showing "none" for a document
they're actively tied to.

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.drop_column() need schema= passed explicitly --
    # see the NOTE in script.py.mako, hit for real by 0005/.../0039.
    bind = op.get_bind()
    schema = bind.get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "calendar_entries",
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        schema=schema,
    )
    op.create_index("ix_calendar_entries_document_id", "calendar_entries", ["document_id"], schema=schema)

    # Raw SQL doesn't pick up schema_translate_map at all -- schema-
    # qualified by hand, same as every other migration here that runs one
    # (0005, 0023, ...).
    bind.execute(
        sa.text(
            f'UPDATE "{schema}".calendar_entries SET document_id = (policy_ref->>\'document_id\')::integer '
            "WHERE policy_ref->>'type' = 'refresh_document' AND policy_ref->>'document_id' IS NOT NULL"
        )
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_index("ix_calendar_entries_document_id", table_name="calendar_entries", schema=schema)
    op.drop_column("calendar_entries", "document_id", schema=schema)
