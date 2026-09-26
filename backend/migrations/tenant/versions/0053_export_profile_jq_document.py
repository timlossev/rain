"""export_profiles.jq_document_id: the JSON-transform ruleset picked on
Assets/Tickets Export (rain.modules.assets.router/rain.modules.tickets.
router, both sharing _jq_transform_fields.html) wasn't part of what
"Save as a reusable profile" actually saved -- format/columns round-
tripped through a saved profile, but the jq document picked alongside
them didn't, so reloading a profile silently dropped it. NULL means "no
saved ruleset" (the pre-existing, only possible state for every row
before this column existed). ON DELETE SET NULL, not CASCADE: deleting
the document a profile's jq step pointed at shouldn't take the whole
profile down with it, just fall back to the plain row export.

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-26
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column("export_profiles", sa.Column("jq_document_id", sa.Integer(), nullable=True), schema=schema)
    op.create_foreign_key(
        "fk_export_profiles_jq_document_id",
        "export_profiles",
        "documents",
        ["jq_document_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_constraint("fk_export_profiles_jq_document_id", "export_profiles", schema=schema, type_="foreignkey")
    op.drop_column("export_profiles", "jq_document_id", schema=schema)
