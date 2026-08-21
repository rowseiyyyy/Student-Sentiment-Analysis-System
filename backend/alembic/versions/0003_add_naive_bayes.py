"""add naive bayes algorithm

Adds Naive Bayes to the TrainingAlgorithm and AlgorithmName enums,
and adds naive_bayes_prediction / naive_bayes_confidence columns to
the predictions table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add Naive Bayes columns to predictions table
    op.add_column(
        "predictions",
        sa.Column("naive_bayes_prediction", sa.String(50), nullable=True),
    )
    op.add_column(
        "predictions",
        sa.Column("naive_bayes_confidence", sa.Float, nullable=True),
    )

    # For MySQL: alter enum columns to include the new value "Naive Bayes"
    # SQLite does not support ALTER TABLE MODIFY; the table will be
    # recreated automatically if using Base.metadata.create_all.
    bind = op.get_bind()
    if bind.engine.name == "mysql":
        op.execute(
            "ALTER TABLE training_history "
            "MODIFY COLUMN algorithm ENUM('SVM','Random Forest','Naive Bayes','BERT') "
            "NOT NULL"
        )
        op.execute(
            "ALTER TABLE predictions "
            "MODIFY COLUMN algorithm_used ENUM('SVM','Random Forest','Naive Bayes','BERT') "
            "NOT NULL"
        )


def downgrade() -> None:
    # Remove columns from predictions table
    op.drop_column("predictions", "naive_bayes_confidence")
    op.drop_column("predictions", "naive_bayes_prediction")

    # For MySQL: revert enum columns to original values
    bind = op.get_bind()
    if bind.engine.name == "mysql":
        op.execute(
            "ALTER TABLE training_history "
            "MODIFY COLUMN algorithm ENUM('SVM','Random Forest','BERT') "
            "NOT NULL"
        )
        op.execute(
            "ALTER TABLE predictions "
            "MODIFY COLUMN algorithm_used ENUM('SVM','Random Forest','BERT') "
            "NOT NULL"
        )

