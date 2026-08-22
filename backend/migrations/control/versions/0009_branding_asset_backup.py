"""Adds control.branding_assets: a durable backup of the branding logo
(rain.db.control_models.BrandingAsset), so rain.web.uploads can restore
it to local disk if it's missing there -- e.g. a container recreated with
no persistent uploads volume (docker-compose.minimal.yml, the
single-container `docker run` quickstart). Only used when S3_BUCKET isn't
set; an S3 bucket is the durable copy instead when it is.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-22

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
        "branding_assets",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("branding_assets", schema=SCHEMA)
