"""Unify Event Promotion Policies and Correlation Rules into one table.

Before this, "does this event become a ticket" was two separate systems
evaluated independently against every new event: TicketRule (single-event
regex match, with a combine_by_title checkbox that folds a repeat onto an
already-open ticket and marks it problematic -- rain.modules.tickets.
service.combine_event_into_ticket, added in 0035) and CorrelationRule
("threshold": N matches in a trailing window spawns a new aggregated
ticket; "ml_anomaly": an online per-rule+group model scores each event).
"threshold" duplicated what combine_by_title already does more simply (one
open ticket accumulating repeat occurrences as comments, flagged
problematic, instead of a fresh ticket per window) -- there was no real
reason to keep both, so this drops "threshold" outright rather than
migrating it.

ticket_rules gains `promotion_type` ("single" | "repetition" |
"ml_anomaly") replacing the old `combine_by_title` boolean (repetition IS
combine_by_title=True, just named for what it does) plus the ml_anomaly
config columns CorrelationRule used to carry alone: `group_by`,
`window_minutes` (ml_anomaly's re-arm cooldown only now -- "repetition"
has no window, it folds a repeat in any time later), `ml_score_threshold`,
`ml_warmup_count`.

Data carried across:
- Every existing ticket_rules row: promotion_type = "repetition" where
  combine_by_title was true, else "single".
- Every correlation_rules row with rule_type = "ml_anomaly": copied into
  a new ticket_rules row (promotion_type = "ml_anomaly"), and its
  correlation_rule_states row(s) (the running model, per group) copied
  into the new ticket_rule_states table against the new row's id.
- Every correlation_rules row with rule_type = "threshold": dropped, per
  above -- there's no equivalent promotion_type to carry it into. Any
  ticket that row already produced keeps existing; only the "which policy
  made this" pointer is lost (tickets.source_correlation_rule_id -> NULL,
  same as it would be if that policy were simply deleted today).
- tickets.source_correlation_rule_id: values pointing at a migrated
  ml_anomaly rule are folded into source_rule_id (now the one "which
  Event Promotion Policy produced this" column for all three types); the
  column itself is then dropped.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column()/op.drop_column()/op.drop_constraint()/
    # op.create_foreign_key() need schema= passed explicitly to respect
    # this env.py's schema_translate_map -- see the NOTE in
    # script.py.mako, hit for real by 0005/.../0037. Raw SQL (op.execute
    # below) doesn't pick it up at all -- schema-qualified by hand instead,
    # same as 0005's bulk_insert.
    bind = op.get_bind()
    schema = bind.get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "ticket_rules",
        sa.Column("promotion_type", sa.String(15), nullable=False, server_default="single"),
        schema=schema,
    )
    op.add_column("ticket_rules", sa.Column("group_by", sa.String(15), nullable=False, server_default="none"), schema=schema)
    op.add_column("ticket_rules", sa.Column("window_minutes", sa.Integer, nullable=False, server_default="5"), schema=schema)
    op.add_column(
        "ticket_rules", sa.Column("ml_score_threshold", sa.Float, nullable=False, server_default="0.7"), schema=schema
    )
    op.add_column(
        "ticket_rules", sa.Column("ml_warmup_count", sa.Integer, nullable=False, server_default="250"), schema=schema
    )
    bind.execute(
        sa.text(f'UPDATE "{schema}".ticket_rules SET promotion_type = \'repetition\' WHERE combine_by_title')
    )

    # Copy every ml_anomaly correlation_rules row into ticket_rules, one
    # at a time (not a bulk INSERT...SELECT) so each new row's id can be
    # captured via RETURNING and used to remap correlation_rule_states/
    # tickets.source_correlation_rule_id below -- there's no column on
    # either that already links back to the old correlation_rules.id
    # otherwise.
    ml_rows = bind.execute(
        sa.text(
            f'SELECT id, name, is_active, ticket_type, match_field, pattern, group_by, window_minutes, '
            f'title_template, severity, asset_match_field, sort_order, ml_score_threshold, ml_warmup_count, '
            f'created_by, created_at FROM "{schema}".correlation_rules WHERE rule_type = \'ml_anomaly\''
        )
    ).mappings().all()

    insert_rule_sql = sa.text(
        f'INSERT INTO "{schema}".ticket_rules '
        "(name, is_active, ticket_type, match_field, pattern, title_template, severity, asset_match_field, "
        "sort_order, promotion_type, group_by, window_minutes, ml_score_threshold, ml_warmup_count, created_by, created_at) "
        "VALUES (:name, :is_active, :ticket_type, :match_field, :pattern, :title_template, :severity, "
        ":asset_match_field, :sort_order, 'ml_anomaly', :group_by, :window_minutes, :ml_score_threshold, "
        ":ml_warmup_count, :created_by, :created_at) RETURNING id"
    )
    old_to_new: dict[int, int] = {}
    for row in ml_rows:
        new_id = bind.execute(insert_rule_sql, dict(row)).scalar_one()
        old_to_new[row["id"]] = new_id

    op.create_table(
        "ticket_rule_states",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rule_id", sa.Integer, sa.ForeignKey("ticket_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ml_model", sa.LargeBinary, nullable=True),
        sa.Column("ml_event_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("rule_id", "group_key", name="uq_ticket_rule_states_rule_group"),
    )
    op.create_index("ix_ticket_rule_states_rule_id", "ticket_rule_states", ["rule_id"])

    if old_to_new:
        state_rows = bind.execute(
            sa.text(
                f'SELECT rule_id, group_key, last_triggered_at, ml_model, ml_event_count '
                f'FROM "{schema}".correlation_rule_states WHERE rule_id = ANY(:rule_ids)'
            ),
            {"rule_ids": list(old_to_new.keys())},
        ).mappings().all()
        insert_state_sql = sa.text(
            f'INSERT INTO "{schema}".ticket_rule_states '
            "(rule_id, group_key, last_triggered_at, ml_model, ml_event_count) "
            "VALUES (:rule_id, :group_key, :last_triggered_at, :ml_model, :ml_event_count)"
        )
        for row in state_rows:
            bind.execute(insert_state_sql, {**dict(row), "rule_id": old_to_new[row["rule_id"]]})

        update_tickets_sql = sa.text(
            f'UPDATE "{schema}".tickets SET source_rule_id = :new_id WHERE source_correlation_rule_id = :old_id'
        )
        for old_id, new_id in old_to_new.items():
            bind.execute(update_tickets_sql, {"old_id": old_id, "new_id": new_id})

    op.drop_constraint("tickets_source_correlation_rule_id_fkey", "tickets", type_="foreignkey", schema=schema)
    op.drop_column("tickets", "source_correlation_rule_id", schema=schema)

    op.drop_table("correlation_rule_states")
    op.drop_table("correlation_rules")

    op.drop_column("ticket_rules", "combine_by_title", schema=schema)


def downgrade() -> None:
    # Best-effort, lossy -- same convention 0006's downgrade already
    # established for a dropped feature (re-adds the shape, not the
    # historical per-row data): the "threshold" correlation_rules rows
    # this dropped have no ticket_rules equivalent to reconstruct, and
    # ml_anomaly rows/state that got copied across stay in ticket_rules
    # rather than being copied back out.
    bind = op.get_bind()
    schema = bind.get_execution_options()["schema_translate_map"][None]

    op.add_column(
        "ticket_rules", sa.Column("combine_by_title", sa.Boolean, nullable=False, server_default="false"), schema=schema
    )
    bind.execute(
        sa.text(f'UPDATE "{schema}".ticket_rules SET combine_by_title = true WHERE promotion_type = \'repetition\'')
    )

    op.create_table(
        "correlation_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("rule_type", sa.String(15), nullable=False, server_default="threshold"),
        sa.Column("ticket_type", sa.String(15), nullable=False),
        sa.Column("match_field", sa.String(15), nullable=False, server_default="message"),
        sa.Column("pattern", sa.String(500), nullable=False),
        sa.Column("group_by", sa.String(15), nullable=False, server_default="none"),
        sa.Column("threshold_count", sa.Integer, nullable=False, server_default="5"),
        sa.Column("window_minutes", sa.Integer, nullable=False, server_default="5"),
        sa.Column("title_template", sa.String(255), nullable=False, server_default="{count} matching events in {window}m"),
        sa.Column("severity", sa.String(15), nullable=False, server_default="medium"),
        sa.Column("asset_match_field", sa.String(15), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ml_score_threshold", sa.Float, nullable=False, server_default="0.7"),
        sa.Column("ml_warmup_count", sa.Integer, nullable=False, server_default="250"),
        sa.Column("created_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "correlation_rule_states",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rule_id", sa.Integer, sa.ForeignKey("correlation_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ml_model", sa.LargeBinary, nullable=True),
        sa.Column("ml_event_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("rule_id", "group_key", name="uq_correlation_rule_states_rule_group"),
    )

    op.add_column(
        "tickets",
        sa.Column("source_correlation_rule_id", sa.Integer, sa.ForeignKey("correlation_rules.id", ondelete="SET NULL")),
        schema=schema,
    )

    op.drop_table("ticket_rule_states")
    op.drop_column("ticket_rules", "ml_warmup_count", schema=schema)
    op.drop_column("ticket_rules", "ml_score_threshold", schema=schema)
    op.drop_column("ticket_rules", "window_minutes", schema=schema)
    op.drop_column("ticket_rules", "group_by", schema=schema)
    op.drop_column("ticket_rules", "promotion_type", schema=schema)
