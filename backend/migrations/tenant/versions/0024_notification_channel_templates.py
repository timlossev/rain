"""Notification channels: adds message_template/subject_template (plain
text, {{ticket_number}}-style placeholders -- see rain.modules.tickets.
notifications.render_template) so the Slack/email text a Platform
Response Rule sends is admin-editable instead of a fixed Python string.
Also widens channel_type's practical range to include "webhook" (no
column change needed -- it was already a plain String(15)), referencing
an existing WebhookConfig the same way Platform Response Rules' own
"webhook" action does.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() respects schema_translate_map when given schema=
    # explicitly -- see the NOTE in script.py.mako, hit for real by
    # 0005/.../0023.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "notification_channels",
        sa.Column("message_template", sa.Text, nullable=False, server_default=""),
        schema=schema,
    )
    op.add_column(
        "notification_channels",
        sa.Column("subject_template", sa.String(255), nullable=True),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("notification_channels", "subject_template", schema=schema)
    op.drop_column("notification_channels", "message_template", schema=schema)
