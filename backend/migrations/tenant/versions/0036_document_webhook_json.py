"""documents.webhook_response_is_json / webhook_json_path: opt-in JSON
handling for a document's "Refresh from webhook" response -- see
rain.modules.documents.service.refresh_from_webhook and Document's own
docstring (rain.db.tenant_models) for the exact semantics.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "documents",
        sa.Column("webhook_response_is_json", sa.Boolean, nullable=False, server_default="false"),
        schema=schema,
    )
    op.add_column("documents", sa.Column("webhook_json_path", sa.Text, nullable=True), schema=schema)


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "webhook_json_path", schema=schema)
    op.drop_column("documents", "webhook_response_is_json", schema=schema)
