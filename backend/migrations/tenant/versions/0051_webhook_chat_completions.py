"""webhook_configs gains a "kind" ("generic" | "chat_completions") plus
three columns only a chat_completions-kind row uses: chat_model,
chat_system_prompt, and chat_memory_document_id (the "shared project
memory / client-wide context" document). See WebhookConfig's own
docstring in rain.db.tenant_models for why this is one table with a
kind switch rather than a second model -- url/headers/timeout_seconds/
success_codes/alert_on_failure stay meaningful for both kinds, only the
request body construction differs.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "webhook_configs",
        sa.Column("kind", sa.String(20), nullable=False, server_default="generic"),
        schema=schema,
    )
    op.add_column("webhook_configs", sa.Column("chat_model", sa.String(255), nullable=True), schema=schema)
    op.add_column("webhook_configs", sa.Column("chat_system_prompt", sa.Text(), nullable=True), schema=schema)
    op.add_column("webhook_configs", sa.Column("chat_memory_document_id", sa.Integer(), nullable=True), schema=schema)
    # No schema= here -- op.create_foreign_key (unlike add_column/
    # drop_column) already resolves schema_translate_map correctly on
    # its own, per this migration package's own script.py.mako NOTE.
    op.create_foreign_key(
        "fk_webhook_configs_chat_memory_document_id",
        "webhook_configs",
        "documents",
        ["chat_memory_document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_constraint("fk_webhook_configs_chat_memory_document_id", "webhook_configs", schema=schema, type_="foreignkey")
    op.drop_column("webhook_configs", "chat_memory_document_id", schema=schema)
    op.drop_column("webhook_configs", "chat_system_prompt", schema=schema)
    op.drop_column("webhook_configs", "chat_model", schema=schema)
    op.drop_column("webhook_configs", "kind", schema=schema)
