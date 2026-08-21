"""tickets.title: widen VARCHAR(255) -> VARCHAR(500). Titles built from a
syslog event's message (rain.modules.tickets.rules.apply_rule and
rain.modules.tickets.correlation's rule/ML firing) were getting silently
truncated at the old limit before they ever reached the DB (see
rain.modules.tickets.service.create_ticket) -- long inbound log lines
routinely exceed 255 characters.

Postgres refuses to ALTER TYPE a column that a generated column depends
on ("cannot alter type of a column used by a generated column") -- 0023's
tickets.search_vector is GENERATED ALWAYS AS (...) STORED off title among
others, so it (and its GIN index) has to come off and get put back rather
than just running a plain ALTER COLUMN.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must exactly match 0023's generated expression -- dropped and recreated
# verbatim here, not altered, so re-running search on existing rows keeps
# producing identical tsvectors.
_SEARCH_VECTOR_EXPR = """
    setweight(to_tsvector('english', coalesce(ticket_number, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B')
"""


def upgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.execute(f"DROP INDEX IF EXISTS {schema}.ix_tickets_search_vector")
    op.execute(f"ALTER TABLE {schema}.tickets DROP COLUMN search_vector")
    op.alter_column(
        "tickets", "title",
        existing_type=sa.String(255),
        type_=sa.String(500),
        schema=schema,
    )
    op.execute(
        f"""
        ALTER TABLE {schema}.tickets ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({_SEARCH_VECTOR_EXPR}) STORED
        """
    )
    op.execute(f"CREATE INDEX ix_tickets_search_vector ON {schema}.tickets USING GIN (search_vector)")


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.execute(f"DROP INDEX IF EXISTS {schema}.ix_tickets_search_vector")
    op.execute(f"ALTER TABLE {schema}.tickets DROP COLUMN search_vector")
    # Existing rows may already be longer than 255 -- truncate first so the
    # narrowing ALTER doesn't fail outright on downgrade.
    op.execute(f'UPDATE "{schema}".tickets SET title = left(title, 255)')
    op.alter_column(
        "tickets", "title",
        existing_type=sa.String(500),
        type_=sa.String(255),
        schema=schema,
    )
    op.execute(
        f"""
        ALTER TABLE {schema}.tickets ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({_SEARCH_VECTOR_EXPR}) STORED
        """
    )
    op.execute(f"CREATE INDEX ix_tickets_search_vector ON {schema}.tickets USING GIN (search_vector)")
