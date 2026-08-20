"""password_reset_tokens: self-service "Forgot password?" for a local
(non-LDAP/SAML) account. Same shape as control.sessions -- an opaque
random token, only its sha256 hash stored, so a DB leak alone can't be
used to reset anyone's password.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-20

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_control_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_table("password_reset_tokens", schema=SCHEMA)
