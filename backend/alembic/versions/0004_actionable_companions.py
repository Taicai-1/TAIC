"""add actionable companions tables and fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_all()/ensure_columns() run before Alembic at startup, so every
    # object here may already exist — guard each one to keep the chain unblocked.
    inspector = sa.inspect(op.get_bind())

    # Add enabled_plugins to agents
    agent_columns = {c["name"] for c in inspector.get_columns("agents")}
    if "enabled_plugins" not in agent_columns:
        op.add_column("agents", sa.Column("enabled_plugins", sa.Text(), nullable=True))

    # Create user_google_tokens table
    if not inspector.has_table("user_google_tokens"):
        op.create_table(
            "user_google_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
            ),
            sa.Column("access_token", sa.Text(), nullable=False),
            sa.Column("refresh_token", sa.Text(), nullable=False),
            sa.Column("token_expiry", sa.DateTime(), nullable=False),
            sa.Column("granted_scopes", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_user_google_tokens_user_id", "user_google_tokens", ["user_id"], unique=True)

    if inspector.has_table("action_executions"):
        return

    # Create action_executions table
    op.create_table(
        "action_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("plugin_name", sa.String(64), nullable=False),
        sa.Column("action_name", sa.String(64), nullable=False),
        sa.Column("action_params", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_confirmation"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_action_executions_agent", "action_executions", ["agent_id"])
    op.create_index("idx_action_executions_user", "action_executions", ["user_id"])
    op.create_index("idx_action_executions_status", "action_executions", ["status"])


def downgrade() -> None:
    op.drop_table("action_executions")
    op.drop_table("user_google_tokens")
    op.drop_column("agents", "enabled_plugins")
