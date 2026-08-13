"""chg_number_seq: ticket-number sequence for the new "change" ticket type,
same pattern as inc_number_seq/vuln_number_seq from 0002_ticketing.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-13
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.schema import CreateSequence, DropSequence
from sqlalchemy.schema import Sequence as SASequence

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.execute() with a real DDL construct (CreateSequence) respects this
    # env.py's schema_translate_map correctly -- see 0002_ticketing.py and
    # the NOTE in script.py.mako for why op.create_sequence() isn't used.
    op.execute(CreateSequence(SASequence("chg_number_seq")))


def downgrade() -> None:
    op.execute(DropSequence(SASequence("chg_number_seq")))
