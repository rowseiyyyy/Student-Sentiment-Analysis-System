"""add likert_sentiment, likert_average to evaluations

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22

Supports deterministic Likert-scale (1-5) scoring, computed independently
of the text sentiment pipeline via app.services.likert.classify_likert.
See app/models/evaluation.py.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("likert_sentiment", sa.String(20), nullable=True))
    op.add_column("evaluations", sa.Column("likert_average", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("evaluations", "likert_average")
    op.drop_column("evaluations", "likert_sentiment")