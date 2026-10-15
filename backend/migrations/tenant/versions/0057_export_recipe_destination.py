"""export_recipes destination fields, mirroring 0054's own addition to
export_profiles: a recipe's run today always becomes a browser
download. This adds save_to_document (false preserves today's
always-download behavior for every existing row), destination_document_id
(the document to overwrite; ON DELETE SET NULL, same reasoning as
assembly_filter_document_id), destination_title (used only when
creating a new document rather than overwriting one), and
destination_is_shareable (Trust Center flag applied right after the
run writes into the document).

No xlsx concern here the way 0054 has for export_profiles -- a
recipe's output is always one JSON document (see ExportRecipe's own
docstring), so there's no format to gate on.

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "export_recipes",
        sa.Column("save_to_document", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=schema,
    )
    op.add_column("export_recipes", sa.Column("destination_document_id", sa.Integer(), nullable=True), schema=schema)
    op.add_column("export_recipes", sa.Column("destination_title", sa.String(length=255), nullable=True), schema=schema)
    op.add_column(
        "export_recipes",
        sa.Column("destination_is_shareable", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=schema,
    )
    op.create_foreign_key(
        "fk_export_recipes_destination_document_id",
        "export_recipes",
        "documents",
        ["destination_document_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_constraint("fk_export_recipes_destination_document_id", "export_recipes", schema=schema, type_="foreignkey")
    op.drop_column("export_recipes", "destination_is_shareable", schema=schema)
    op.drop_column("export_recipes", "destination_title", schema=schema)
    op.drop_column("export_recipes", "destination_document_id", schema=schema)
    op.drop_column("export_recipes", "save_to_document", schema=schema)
