"""webhook_configs.alert_on_failure: opt-in syslog alert (through the same
rule engine real syslog traffic goes through) whenever a call to a webhook
fails or times out, checked by both callers (Platform Response Rules'
"webhook" action and a Document's "populate from webhook" refresh).

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() doesn't respect this env.py's schema_translate_map --
    # see the NOTE in script.py.mako, hit for real by 0005/.../0020.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "webhook_configs",
        sa.Column("alert_on_failure", sa.Boolean, nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("webhook_configs", "alert_on_failure", schema=schema)
