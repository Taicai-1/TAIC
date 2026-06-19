"""missions feature: missions, mission_events, mission_recaps + mission_id columns

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # create_all() runs before Alembic at startup, so tables/columns may already
    # exist on a fresh DB — guard each create.
    if not inspector.has_table("missions"):
        op.create_table(
            "missions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column(
                "agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
            ),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("recap_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("recap_weekday", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recap_hour", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("mission_events"):
        op.create_table(
            "mission_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "mission_id", sa.Integer(), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=10), nullable=False, server_default="upload"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_mission_events_mission_date", "mission_events", ["mission_id", "event_date"])

    if not inspector.has_table("mission_recaps"):
        op.create_table(
            "mission_recaps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "mission_id", sa.Integer(), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("email_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("trigger", sa.String(length=10), nullable=False, server_default="scheduled"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # Add nullable mission_id columns to existing tables (idempotent).
    existing_doc_cols = {c["name"] for c in inspector.get_columns("documents")}
    if "mission_id" not in existing_doc_cols:
        op.add_column("documents", sa.Column("mission_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "documents_mission_id_fkey", "documents", "missions", ["mission_id"], ["id"], ondelete="CASCADE"
        )
        op.create_index("ix_documents_mission_id", "documents", ["mission_id"])

    existing_conv_cols = {c["name"] for c in inspector.get_columns("conversations")}
    if "mission_id" not in existing_conv_cols:
        op.add_column("conversations", sa.Column("mission_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "conversations_mission_id_fkey", "conversations", "missions", ["mission_id"], ["id"], ondelete="CASCADE"
        )
        op.create_index("ix_conversations_mission_id", "conversations", ["mission_id"])


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE documents DROP COLUMN IF EXISTS mission_id"))
    conn.execute(sa.text("ALTER TABLE conversations DROP COLUMN IF EXISTS mission_id"))
    conn.execute(sa.text("DROP TABLE IF EXISTS mission_recaps CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS mission_events CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS missions CASCADE"))
