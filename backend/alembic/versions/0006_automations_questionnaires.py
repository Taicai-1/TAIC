"""rebuild questionnaires as standalone automations entity

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Clean rebuild decided in the 2026-06-10 spec: no data migration from the
    # legacy agent-based questionnaire tables.
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_answers CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_responses CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_questions CASCADE"))

    # ALTER TABLE agents needs an ACCESS EXCLUSIVE lock on the busiest table in
    # the app; with lock_timeout=5s during a rolling deploy this can fail. Run
    # it under a savepoint so a lock timeout can't roll back the whole rebuild —
    # leftover welcome_message/closing_message columns are unused and harmless.
    try:
        with conn.begin_nested():
            conn.execute(sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS welcome_message"))
            conn.execute(sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS closing_message"))
    except Exception as e:  # pragma: no cover - timing dependent
        print(f"0006: agents column drop deferred (lock contention?): {e}", flush=True)

    # create_all() runs before Alembic at startup, so the new tables may already
    # exist on a fresh database — guard each create.
    inspector = sa.inspect(conn)

    if not inspector.has_table("questionnaires"):
        op.create_table(
            "questionnaires",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
            ),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("questionnaire_questions"):
        op.create_table(
            "questionnaire_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "questionnaire_id",
                sa.Integer(),
                sa.ForeignKey("questionnaires.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("question_type", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("options", sa.Text(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("questionnaire_responses"):
        op.create_table(
            "questionnaire_responses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "questionnaire_id",
                sa.Integer(),
                sa.ForeignKey("questionnaires.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("respondent_email", sa.String(length=255), nullable=False),
            sa.Column("respondent_name", sa.String(length=255), nullable=True),
            sa.Column("token", sa.String(length=64), nullable=False, unique=True, index=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("email_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("invited_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("questionnaire_id", "respondent_email", name="uq_response_questionnaire_email"),
        )

    if not inspector.has_table("questionnaire_answers"):
        op.create_table(
            "questionnaire_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "response_id",
                sa.Integer(),
                sa.ForeignKey("questionnaire_responses.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "question_id",
                sa.Integer(),
                sa.ForeignKey("questionnaire_questions.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("answer_text", sa.Text(), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
        )

    # Ensure the dedupe constraint exists even when create_all() built the table
    # from an older model definition.
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_response_questionnaire_email') THEN "
            "ALTER TABLE questionnaire_responses ADD CONSTRAINT uq_response_questionnaire_email "
            "UNIQUE (questionnaire_id, respondent_email); "
            "END IF; "
            "END $$"
        )
    )

    # Guard: make user_id nullable on DBs where create_all() ran with the old
    # NOT NULL model (before the SET NULL fix).
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS ("
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'questionnaires' AND column_name = 'user_id' AND is_nullable = 'NO'"
            ") THEN "
            "ALTER TABLE questionnaires ALTER COLUMN user_id DROP NOT NULL; "
            "END IF; "
            "END $$"
        )
    )

    # Guard: recreate the user_id FK with ON DELETE SET NULL on DBs where the
    # old NO ACTION FK still exists (confdeltype 'a' = NO ACTION).
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS ("
            "SELECT 1 FROM pg_constraint c "
            "JOIN pg_class t ON c.conrelid = t.oid "
            "WHERE t.relname = 'questionnaires' AND c.contype = 'f' AND c.confdeltype = 'a' "
            "AND EXISTS ("
            "SELECT 1 FROM pg_attribute a "
            "WHERE a.attrelid = t.oid AND a.attname = 'user_id' AND a.attnum = ANY(c.conkey)"
            ")"
            ") THEN "
            "ALTER TABLE questionnaires DROP CONSTRAINT questionnaires_user_id_fkey; "
            "ALTER TABLE questionnaires ADD CONSTRAINT questionnaires_user_id_fkey "
            "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL; "
            "END IF; "
            "END $$"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_answers CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_responses CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_questions CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaires CASCADE"))
    conn.execute(sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS welcome_message TEXT"))
    conn.execute(sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS closing_message TEXT"))
