"""documents.tags: optional, freeform tags on a document -- a plain
Postgres text[] column rather than a normalized tags/document_tags join
table, since (a) the whole point here is feeding them into the existing
generated search_vector tsvector (rain.modules.search), and a GENERATED
column's expression can only reference columns on the same row, never a
join, and (b) nothing about this ask needs a tenant-wide tag registry,
autocomplete-across-documents, or tag-scoped browsing -- just "tag a
document, find it by that tag later," which an array column does
directly.

search_vector's GENERATED expression has to be dropped and re-added
wholesale to add tags into it -- Postgres has no ALTER ... EXPRESSION
for a generated column -- widening 0023's original 3-part expression
(doc_number/title weight A, description weight B) with tags folded in
at weight B, same tier as description: a deliberate, concise label
someone chose for this document, not filler text, but title/doc_number
(weight A) still wins a tie-break.

Folding an array into one to_tsvector() call needs it as a single text
blob first, and Postgres requires a GENERATED column's expression to be
IMMUTABLE -- confirmed live that neither array_to_string(tags, ' ')
nor a plain tags::text cast qualifies (both are STABLE, not IMMUTABLE,
in this Postgres version: `ALTER TABLE ... ADD COLUMN ... GENERATED`
against either raised "generation expression is not immutable"), and
array_to_tsvector(tags) -- immutable, but produces lexemes that don't
participate in `@@` matching via websearch_to_tsquery at all (confirmed
live: even a plain, no-stemming-needed tag like "oncall" came back
false) -- not a usable substitute. A tiny SQL wrapper function marked
IMMUTABLE explicitly is the standard, documented way around a built-in
that's merely STABLE for reasons that don't actually apply here (this
tenant schema's own collation/locale aren't going to change under a
STORED column); scoped to this tenant schema like everything else here,
so dropping the schema drops it too, no shared/public-schema leftover.

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.drop_column() need schema= passed explicitly to
    # respect this env.py's schema_translate_map; op.execute() (raw SQL,
    # below) does not pick it up at all -- schema-qualified by hand, same
    # as every other migration here that touches a GENERATED column or
    # runs raw SQL (0005, 0023, ...).
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "documents",
        sa.Column("tags", postgresql.ARRAY(sa.String), nullable=False, server_default="{}"),
        schema=schema,
    )

    op.execute(
        f"""
        CREATE FUNCTION "{schema}".immutable_array_to_string(text[], text) RETURNS text AS $$
            SELECT array_to_string($1, $2)
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE
        """
    )

    op.execute(f"DROP INDEX {schema}.ix_documents_search_vector")
    op.execute(f"ALTER TABLE {schema}.documents DROP COLUMN search_vector")
    op.execute(
        f"""
        ALTER TABLE {schema}.documents ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(doc_number, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(
                to_tsvector('english', coalesce("{schema}".immutable_array_to_string(tags, ' '), '')), 'B'
            ) ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B')
        ) STORED
        """
    )
    op.execute(f"CREATE INDEX ix_documents_search_vector ON {schema}.documents USING GIN (search_vector)")


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]

    op.execute(f"DROP INDEX {schema}.ix_documents_search_vector")
    # The generated column has to go before the function it calls --
    # Postgres tracks that as a dependency (confirmed live: dropping the
    # function first raises "cannot drop function ... because other
    # objects depend on it").
    op.execute(f"ALTER TABLE {schema}.documents DROP COLUMN search_vector")
    op.execute(f'DROP FUNCTION "{schema}".immutable_array_to_string(text[], text)')
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
    op.execute(f"CREATE INDEX ix_documents_search_vector ON {schema}.documents USING GIN (search_vector)")

    op.drop_column("documents", "tags", schema=schema)
