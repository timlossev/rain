"""initial control schema

Revision ID: 0001
Revises:
Create Date: 2026-08-12

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(63), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.UniqueConstraint("schema_name", name="uq_tenants_schema_name"),
        schema=SCHEMA,
    )
    op.create_index("ix_control_tenants_slug", "tenants", ["slug"], schema=SCHEMA)

    op.create_table(
        "roles",
        sa.Column("key", sa.String(63), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("permissions", postgresql.JSONB, nullable=False, server_default="[]"),
        schema=SCHEMA,
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role_key", sa.String(63), sa.ForeignKey(f"{SCHEMA}.roles.key"), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema=SCHEMA,
    )
    op.create_index("ix_control_users_email", "users", ["email"], schema=SCHEMA)
    op.create_index("ix_control_users_tenant_id", "users", ["tenant_id"], schema=SCHEMA)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "active_tenant_id", sa.Integer, sa.ForeignKey(f"{SCHEMA}.tenants.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        schema=SCHEMA,
    )
    op.create_index("ix_control_sessions_token_hash", "sessions", ["token_hash"], schema=SCHEMA)

    op.create_table(
        "global_config",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_by", sa.Integer, sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "auth_providers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider_type", sa.String(31), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        schema=SCHEMA,
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "actor_user_id", sa.Integer, sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("action", sa.String(127), nullable=False),
        sa.Column("entity_type", sa.String(127), nullable=False),
        sa.Column("entity_id", sa.String(127), nullable=True),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )

    op.execute(
        f"""
        INSERT INTO {SCHEMA}.roles (key, name, description, permissions) VALUES
        ('internal_admin', 'Internal Admin',
         'Full platform access: all tenants, branding, integrations, users.',
         '["*"]'::jsonb),
        ('client', 'Client',
         'Full access scoped to their own tenant.',
         '["tenant:*"]'::jsonb)
        """
    )

    # Auth provider placeholders -- only "local" is functional in this
    # milestone; the rest exist so the Admin UI can show them as
    # "coming soon" without a later schema change.
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.auth_providers (provider_type, name, config, is_enabled) VALUES
        ('local', 'Local (email + password)', '{{}}'::jsonb, true),
        ('oidc', 'OpenID Connect', '{{}}'::jsonb, false),
        ('saml', 'SAML', '{{}}'::jsonb, false),
        ('ldap', 'LDAP', '{{}}'::jsonb, false)
        """
    )


def downgrade() -> None:
    op.drop_table("audit_log", schema=SCHEMA)
    op.drop_table("auth_providers", schema=SCHEMA)
    op.drop_table("global_config", schema=SCHEMA)
    op.drop_table("sessions", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
    op.drop_table("roles", schema=SCHEMA)
    op.drop_table("tenants", schema=SCHEMA)
