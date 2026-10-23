"""add optimizations table and started_at on datasets

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("datasets", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "optimizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("params", JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("result_status", sa.String(16), nullable=True),
        sa.Column("objective", sa.Float(), nullable=True),
        sa.Column("uplift_pct", sa.Float(), nullable=True),
        sa.Column("result", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_optimizations_dataset_id", "optimizations", ["dataset_id"])
    op.create_index("ix_optimizations_status", "optimizations", ["status"])
    op.create_index("ix_optimizations_created_at", "optimizations", ["created_at"])


def downgrade() -> None:
    op.drop_table("optimizations")
    with op.batch_alter_table("datasets") as batch:
        batch.drop_column("started_at")
