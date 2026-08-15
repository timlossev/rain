"""Assets get a pretty, human-readable identifier (CI-000123 --
Configuration Item) alongside their database id, the same INC/VULN/CHG/
DOC-style 6-digit zero-padded scheme every other record type already
uses. Existing assets are backfilled in id order so the numbering is at
least stable and monotonic even though it wasn't tracked from creation;
new assets get one from ci_number_seq going forward (see
rain.modules.assets.service._next_ci_number).

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import CreateSequence, DropSequence
from sqlalchemy.schema import Sequence as SASequence

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.alter_column()/op.create_index()/
    # op.create_unique_constraint() all need schema= passed explicitly to
    # respect this env.py's schema_translate_map -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0024. CreateSequence is the
    # one DDL construct that already does the right thing on its own (see
    # 0003/0014).
    bind = op.get_bind()
    schema = bind.get_execution_options()["schema_translate_map"][None]

    op.add_column("assets", sa.Column("ci_number", sa.String(31), nullable=True), schema=schema)

    # Backfill: oldest asset first, so CI-000001 is whichever asset has
    # been around longest -- not meaningful in any deeper sense, just
    # stable and monotonic.
    bind.execute(
        sa.text(
            f'UPDATE "{schema}".assets AS a '
            "SET ci_number = 'CI-' || LPAD(sub.rn::text, 6, '0') "
            f'FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM "{schema}".assets) AS sub '
            "WHERE a.id = sub.id"
        )
    )

    op.alter_column("assets", "ci_number", existing_type=sa.String(31), nullable=False, schema=schema)
    op.create_unique_constraint("uq_assets_ci_number", "assets", ["ci_number"], schema=schema)
    op.create_index("ix_assets_ci_number", "assets", ["ci_number"], schema=schema)

    op.execute(CreateSequence(SASequence("ci_number_seq")))
    count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{schema}".assets')).scalar()
    if count:
        # Marks `count` as already consumed, so the *next* nextval() call
        # (the first asset created after this migration) returns count + 1,
        # continuing on from the backfill instead of colliding with it.
        bind.execute(sa.text(f"SELECT setval('\"{schema}\".ci_number_seq', :n, true)"), {"n": count})


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.get_execution_options()["schema_translate_map"][None]
    op.execute(DropSequence(SASequence("ci_number_seq")))
    op.drop_index("ix_assets_ci_number", table_name="assets", schema=schema)
    op.drop_constraint("uq_assets_ci_number", "assets", type_="unique", schema=schema)
    op.drop_column("assets", "ci_number", schema=schema)
