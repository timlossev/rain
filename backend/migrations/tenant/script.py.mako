"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

NOTE on schema_translate_map (read before using op.bulk_insert, op.add_column,
or op.drop_column): this env.py resolves the target tenant schema purely via
connection.execution_options(schema_translate_map=...), no search_path, no -x
arg baked into statements. op.create_table()/op.create_index()/
op.create_foreign_key() and op.execute(<a real DDL construct, e.g.
CreateSequence>) all pick that up correctly. op.bulk_insert() and
op.add_column()/op.drop_column() do NOT -- confirmed via two real runs
(0005, 0006 in this same revision history): both emitted unqualified SQL and
raised UndefinedTableError. Workarounds, in order of preference:
  - op.add_column()/op.drop_column(): pass schema=<tenant schema> explicitly.
  - DML (inserts/updates/deletes): read the schema off the bind and
    fully-qualify your own raw SQL:
        schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
        op.execute(sa.text(f'INSERT INTO "{schema}".some_table (...) VALUES (...)'))
Don't assume any other op.* helper translates correctly without checking --
if in doubt, run it for real against a tenant schema before trusting it.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
