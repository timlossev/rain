"""Enables the pgvector extension. Extensions are per-database, not
per-schema -- every tenant schema lives in this one Postgres database
(schema-per-tenant, not database-per-tenant), so this only needs to run
once here in the control chain rather than once per tenant. Reserves the
`vector` type for the `embedding` columns tenant migration 0023 adds to
tickets/documents (see rain.db.tenant_models.EMBEDDING_DIM) -- unused
until a real embedding source exists, see rain.modules.search.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-15

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
