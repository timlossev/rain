"""export_profiles destination fields: an export's output today always
becomes a browser download, regardless of whether a profile is saved.
This adds the fields that let a saved profile instead describe "write
this into a Document" -- save_to_document (false preserves today's
always-download behavior for every existing row), destination_document_id
(the document to overwrite; ON DELETE SET NULL for the same reason
jq_document_id is -- a deleted target document shouldn't take the whole
profile down, just fall back to needing a document picked again),
destination_title (used only when creating a new document rather than
overwriting one), and destination_is_shareable (Trust Center flag
applied to the document right after the export writes into it).

A profile with save_to_document=true and destination_document_id set is
what the Calendar's "run a saved export profile" trigger (see
rain.modules.calendar.sweep) requires -- a scheduled run always
overwrites a document that's already been picked by hand once, it never
creates one unattended.

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "export_profiles",
        sa.Column("save_to_document", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=schema,
    )
    op.add_column("export_profiles", sa.Column("destination_document_id", sa.Integer(), nullable=True), schema=schema)
    op.add_column("export_profiles", sa.Column("destination_title", sa.String(length=255), nullable=True), schema=schema)
    op.add_column(
        "export_profiles",
        sa.Column("destination_is_shareable", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=schema,
    )
    op.create_foreign_key(
        "fk_export_profiles_destination_document_id",
        "export_profiles",
        "documents",
        ["destination_document_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_constraint("fk_export_profiles_destination_document_id", "export_profiles", schema=schema, type_="foreignkey")
    op.drop_column("export_profiles", "destination_is_shareable", schema=schema)
    op.drop_column("export_profiles", "destination_title", schema=schema)
    op.drop_column("export_profiles", "destination_document_id", schema=schema)
    op.drop_column("export_profiles", "save_to_document", schema=schema)
