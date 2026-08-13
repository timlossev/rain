"""LDAP auth provider: encrypted connection config + last-sync bookkeeping
on auth_providers, and the columns a synced user needs on users
(auth_source, ldap_dn, and password_hash becoming optional -- an
LDAP-sourced user never gets one, authentication for them always binds
live against the directory instead of checking a local hash).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-14

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.add_column("auth_providers", sa.Column("config_encrypted", sa.LargeBinary, nullable=True), schema=SCHEMA)
    op.add_column(
        "auth_providers", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA
    )
    op.add_column("auth_providers", sa.Column("last_sync_summary", sa.Text, nullable=True), schema=SCHEMA)

    op.add_column(
        "users", sa.Column("auth_source", sa.String(15), nullable=False, server_default="local"), schema=SCHEMA
    )
    op.add_column("users", sa.Column("ldap_dn", sa.String(1024), nullable=True), schema=SCHEMA)
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True, schema=SCHEMA)


def downgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False, schema=SCHEMA)
    op.drop_column("users", "ldap_dn", schema=SCHEMA)
    op.drop_column("users", "auth_source", schema=SCHEMA)

    op.drop_column("auth_providers", "last_sync_summary", schema=SCHEMA)
    op.drop_column("auth_providers", "last_synced_at", schema=SCHEMA)
    op.drop_column("auth_providers", "config_encrypted", schema=SCHEMA)
