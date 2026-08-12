"""document repository (Milestone 3)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import CreateSequence, DropSequence
from sqlalchemy.schema import Sequence as SASequence

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doc_number", sa.String(31), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("uploaded_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("doc_number", name="uq_documents_doc_number"),
    )
    op.create_index("ix_documents_doc_number", "documents", ["doc_number"])

    op.create_table(
        "document_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("linked_type", sa.String(15), nullable=False),
        sa.Column("linked_id", sa.Integer, nullable=False),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "linked_type", "linked_id", name="uq_document_links"),
    )
    op.create_index("ix_document_links_document_id", "document_links", ["document_id"])
    op.create_index("ix_document_links_target", "document_links", ["linked_type", "linked_id"])

    # See migrations/tenant/versions/0002_ticketing.py for why this uses
    # op.execute(CreateSequence(...)) rather than op.create_sequence()
    # (which doesn't exist on the installed Alembic version).
    op.execute(CreateSequence(SASequence("doc_number_seq")))


def downgrade() -> None:
    op.execute(DropSequence(SASequence("doc_number_seq")))
    op.drop_table("document_links")
    op.drop_table("documents")
