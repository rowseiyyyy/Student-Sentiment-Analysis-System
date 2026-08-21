"""add sentiment column to evaluations

Adds a sentiment column to the evaluations (responses) table so the
official production sentiment label is stored directly on each response
row, alongside the prediction record.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("sentiment", sa.String(20), nullable=True))
    op.create_index("ix_evaluations_sentiment", "evaluations", ["sentiment"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evaluations_sentiment", table_name="evaluations")
    op.drop_column("evaluations", "sentiment")
