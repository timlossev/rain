"""documents.is_shareable: opt-in, per-document flag exposing a document
through the client portal's "Shareable documents" tab (rain.modules.
portal.router.portal_form) to *every* visitor, including an anonymous
one, even on a tenant with portal_require_auth on. Off by default -- a
document is private (internal-app-only) unless explicitly marked otherwise, the same
default-locked-down posture portal_require_auth/portal_branded already
take in rain.core.tenant_config.DEFAULTS.

The tab's own label is a tenant_config value (portal_shareable_documents_
label, default "Shareable documents"), not a new column here -- it's
free text an admin sets on Admin > Branding (e.g. "Trust Center"), same
mechanism escalation_webhook_id already uses for a per-tenant portal
setting, so it doesn't need its own migration.

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() needs schema= passed explicitly -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0041.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "documents",
        sa.Column("is_shareable", sa.Boolean(), nullable=False, server_default="false"),
        schema=schema,
    )


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("documents", "is_shareable", schema=schema)
