"""create datasets and dataset_files

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("cols", sa.Integer(), nullable=True),
        sa.Column("warnings_count", sa.Integer(), nullable=True),
        sa.Column("profile", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_datasets_status", "datasets", ["status"])
    op.create_index("ix_datasets_created_at", "datasets", ["created_at"])
    op.create_table(
        "dataset_files",
        sa.Column(
            "dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("content", sa.LargeBinary(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dataset_files")
    op.drop_index("ix_datasets_created_at", table_name="datasets")
    op.drop_index("ix_datasets_status", table_name="datasets")
    op.drop_table("datasets")
