"""export_recipes/export_recipe_steps: a named, ordered list of
ExportRecipeStep rows (each running an existing ExportProfile's export,
then optionally its own jq filter) plus one optional "assembly" filter
run over the collected {label: value} outputs -- the fan-out-then-merge
mechanism that assembles one output document out of several
independently-scoped exports (rain.core.export_recipe), rather than
reshaping a single export the way an ExportProfile's own jq_document_id
already does.

ON DELETE CASCADE from export_recipe_steps.recipe_id to
export_recipes.id (deleting a recipe deletes its steps -- same
parent/child cascade ApprovalFlow/ApprovalFlowStep already uses) and
from export_recipe_steps.export_profile_id to export_profiles.id (a
step with no profile left to run is a hole in the recipe, not a step
with nothing to do -- see ExportRecipeStep's own docstring for why this
is a dormant guarantee today, since nothing deletes an ExportProfile
yet).

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.create_table() doesn't need schema= passed explicitly the way
    # op.add_column() does (see e.g. 0048's own comment on that) -- the
    # connection's own schema_translate_map already covers unqualified
    # table names here, confirmed by every other create_table in this
    # directory (0013, 0032, 0048, ...) using plain inline
    # sa.ForeignKey("other_table.id", ...) with no schema prefix.
    op.create_table(
        "export_recipes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "assembly_filter_document_id",
            sa.Integer,
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "export_recipe_steps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("recipe_id", sa.Integer, sa.ForeignKey("export_recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column(
            "export_profile_id", sa.Integer, sa.ForeignKey("export_profiles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "filter_document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("ix_export_recipe_steps_recipe_id", "export_recipe_steps", ["recipe_id"])


def downgrade() -> None:
    op.drop_index("ix_export_recipe_steps_recipe_id", table_name="export_recipe_steps")
    op.drop_table("export_recipe_steps")
    op.drop_table("export_recipes")
