"""mission recap schedules: table, mission_recaps.schedule_id, backfill

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # create_all() runs before Alembic at startup, so the table/column may
    # already exist on a fresh DB — guard each operation.
    if not inspector.has_table("mission_recap_schedules"):
        op.create_table(
            "mission_recap_schedules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "mission_id", sa.Integer(), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("kind", sa.String(length=10), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=True),
            sa.Column("run_date", sa.Date(), nullable=True),
            sa.Column("hour", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    existing_recap_cols = {c["name"] for c in inspector.get_columns("mission_recaps")}
    if "schedule_id" not in existing_recap_cols:
        op.add_column("mission_recaps", sa.Column("schedule_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "mission_recaps_schedule_id_fkey",
            "mission_recaps",
            "mission_recap_schedules",
            ["schedule_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_mission_recaps_schedule_id", "mission_recaps", ["schedule_id"])

    # Backfill: one recurring schedule per mission that had recap_enabled=true and
    # no schedule yet (idempotent on re-run).
    conn.execute(
        sa.text(
            """
            INSERT INTO mission_recap_schedules
                (mission_id, company_id, kind, weekday, hour, enabled, created_at)
            SELECT m.id, m.company_id, 'recurring', m.recap_weekday, m.recap_hour, true, NOW()
            FROM missions m
            WHERE m.recap_enabled = true
              AND NOT EXISTS (
                  SELECT 1 FROM mission_recap_schedules s WHERE s.mission_id = m.id
              )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE mission_recaps DROP COLUMN IF EXISTS schedule_id"))
    conn.execute(sa.text("DROP TABLE IF EXISTS mission_recap_schedules CASCADE"))
