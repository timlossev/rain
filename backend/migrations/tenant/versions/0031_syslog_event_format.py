"""syslog_events gets event_format (plain|cef|json|kv, from
rain.modules.tickets.event_formats) and parsed_fields (the structured
data that format's parser extracted) -- lets the listener recognize and
work with CEF, JSON, and Splunk-style key=value message bodies instead
of only plain RFC 3164/5424 syslog text, without touching how the
envelope fields (host/program/facility/severity) already get parsed.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly to respect this
    # env.py's schema_translate_map -- see the NOTE in script.py.mako,
    # hit for real by 0005/.../0030.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "syslog_events",
        sa.Column("event_format", sa.String(15), nullable=False, server_default="plain"),
        schema=schema,
    )
    op.add_column(
        "syslog_events",
        sa.Column("parsed_fields", postgresql.JSONB, nullable=True),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("syslog_events", "parsed_fields", schema=schema)
    op.drop_column("syslog_events", "event_format", schema=schema)
