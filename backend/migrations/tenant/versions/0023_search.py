"""Keyword search (rain.modules.search): a DB-generated, always-current
tsvector column on tickets and documents (ticket_number/title/description,
doc_number/title/description respectively), GIN-indexed for ts_rank
scoring instead of a naive ILIKE scan. Also adds a reserved `embedding`
vector(1536) column to both -- unused until a real embedding source
exists (no LLM wired into this app today), but the column/type is ready
so a future semantic-search pass is a backfill, not another migration.
Requires the vector extension (control migration 0006).

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    # op.add_column() respects schema_translate_map when given schema=
    # explicitly; op.execute() (raw SQL, below) does not -- see the NOTE
    # in script.py.mako, hit for real by 0005/.../0022.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.add_column("tickets", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True), schema=schema)
    op.add_column("documents", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True), schema=schema)

    op.execute(
        f"""
        ALTER TABLE {schema}.tickets ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(ticket_number, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B')
        ) STORED
        """
    )
    op.execute(
        f"""
        ALTER TABLE {schema}.documents ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(doc_number, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B')
        ) STORED
        """
    )
    op.execute(f"CREATE INDEX ix_tickets_search_vector ON {schema}.tickets USING GIN (search_vector)")
    op.execute(f"CREATE INDEX ix_documents_search_vector ON {schema}.documents USING GIN (search_vector)")


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.execute(f"DROP INDEX IF EXISTS {schema}.ix_documents_search_vector")
    op.execute(f"DROP INDEX IF EXISTS {schema}.ix_tickets_search_vector")
    op.drop_column("documents", "search_vector", schema=schema)
    op.drop_column("tickets", "search_vector", schema=schema)
    op.drop_column("documents", "embedding", schema=schema)
    op.drop_column("tickets", "embedding", schema=schema)
