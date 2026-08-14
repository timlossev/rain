"""Removes the seeded "oidc" auth_providers row -- SAML is now a real,
implemented provider (see rain.modules.auth.saml_provider); OIDC support
was dropped rather than left as a second unimplemented placeholder.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.execute(f"DELETE FROM {SCHEMA}.auth_providers WHERE provider_type = 'oidc'")


def downgrade() -> None:
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.auth_providers (provider_type, name, config, is_enabled)
        VALUES ('oidc', 'OpenID Connect', '{{}}'::jsonb, false)
        """
    )
