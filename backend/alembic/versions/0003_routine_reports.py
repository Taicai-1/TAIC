"""add routine_reports table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "routine_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_routine_reports_type", "routine_reports", ["type"])
    op.create_index("ix_routine_reports_created_at", "routine_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_routine_reports_created_at", table_name="routine_reports")
    op.drop_index("ix_routine_reports_type", table_name="routine_reports")
    op.drop_table("routine_reports")
