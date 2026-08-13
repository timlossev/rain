"""groups.source/ldap_dn: distinguishes an LDAP-synced group from one
created by hand in Admin > Groups, so a sync run can safely reconcile
(add/update/remove) groups it owns without ever touching a manually
created one that happens to share a name.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column() doesn't respect this env.py's schema_translate_map --
    # see the NOTE in script.py.mako, hit for real by 0005/0006/0013.
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.add_column(
        "groups", sa.Column("source", sa.String(15), nullable=False, server_default="local"), schema=schema
    )
    op.add_column("groups", sa.Column("ldap_dn", sa.String(1024), nullable=True), schema=schema)


def downgrade() -> None:
    schema = op.get_bind().get_execution_options()["schema_translate_map"][None]
    op.drop_column("groups", "ldap_dn", schema=schema)
    op.drop_column("groups", "source", schema=schema)
