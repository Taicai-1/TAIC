"""baseline: stamp existing schema

Revision ID: 0001
Revises: None
Create Date: 2026-04-27

This is the baseline migration. On existing databases, run:
    alembic stamp 0001
to mark the current schema as up-to-date without executing any DDL.

On brand-new databases, the tables are created by SQLAlchemy
Base.metadata.create_all() which is still called before Alembic runs.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baseline: existing schema is already in place.
    pass


def downgrade() -> None:
    # Cannot reverse a baseline stamp.
    pass
