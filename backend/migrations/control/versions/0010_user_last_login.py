"""control.users.last_login_at: stamped by rain.modules.auth.router.
_issue_session on every successful sign-in (local password, LDAP bind, or
SAML ACS -- all three funnel through that one function, so this is the
single place that needs to set it). Nothing populated it before this
migration, so every existing row starts NULL -- "never logged in since
this column existed" is indistinguishable from "never logged in at all"
for an account provisioned before this release, which is an acceptable
one-time gap given the alternative (backfilling from session history)
isn't reliably available either.

Backs the "Last login" column and CSV export on Admin > Users -- the
platform-level access-review evidence FedRAMP AC-2(3)/EUCS IAM-06-style
controls ask for (identify accounts that should be deactivated because
they're no longer in use), which nothing in this schema could produce
before now.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "control"


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("users", "last_login_at", schema=SCHEMA)
