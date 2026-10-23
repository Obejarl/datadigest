"""add queued_at to datasets

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    # Backfill: for existing rows the current attempt started when they were uploaded.
    op.execute("UPDATE datasets SET queued_at = created_at")


def downgrade() -> None:
    with op.batch_alter_table("datasets") as batch:
        batch.drop_column("queued_at")
