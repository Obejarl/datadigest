"""add quality_score to datasets

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: rows profiled before this migration simply have no score.
    op.add_column("datasets", sa.Column("quality_score", sa.Integer(), nullable=True))


def downgrade() -> None:
    # batch mode lets SQLite (which cannot DROP COLUMN in old versions) rebuild the table.
    with op.batch_alter_table("datasets") as batch:
        batch.drop_column("quality_score")
