"""add date_awareness_enabled to agents

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ensure_columns() runs before Alembic at startup, so the column may
    # already exist — guard to keep the migration chain unblocked.
    inspector = sa.inspect(op.get_bind())
    agent_columns = {c["name"] for c in inspector.get_columns("agents")}
    if "date_awareness_enabled" in agent_columns:
        return

    op.add_column(
        "agents",
        sa.Column("date_awareness_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("agents", "date_awareness_enabled")
