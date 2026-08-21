"""add new model prediction fields

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-18

The Prediction ORM model gained XGBoost, DeBERTa, and RoBERTa result
columns.  Existing databases created at revision 0004 need these nullable
columns before SQLAlchemy can read or write prediction rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("xgb_prediction", sa.String(20), nullable=True))
    op.add_column("predictions", sa.Column("xgb_confidence", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("deberta_prediction", sa.String(20), nullable=True))
    op.add_column("predictions", sa.Column("deberta_confidence", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("roberta_prediction", sa.String(20), nullable=True))
    op.add_column("predictions", sa.Column("roberta_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "roberta_confidence")
    op.drop_column("predictions", "roberta_prediction")
    op.drop_column("predictions", "deberta_confidence")
    op.drop_column("predictions", "deberta_prediction")
    op.drop_column("predictions", "xgb_confidence")
    op.drop_column("predictions", "xgb_prediction")
