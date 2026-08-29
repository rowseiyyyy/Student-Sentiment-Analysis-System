"""drop legacy svm/random_forest/naive_bayes/bert prediction columns

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-30

The active pipeline is now exclusively XGBoost, DeBERTa, and RoBERTa
(plus the DeBERTa+RoBERTa ensemble). The four legacy classical/BERT
columns are removed from the predictions table; historical rows that
held those values are no longer readable via this schema.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the 8 legacy columns (4 predictions + 4 confidences).
    for col in (
        "svm_prediction",
        "svm_confidence",
        "random_forest_prediction",
        "random_forest_confidence",
        "naive_bayes_prediction",
        "naive_bayes_confidence",
        "bert_prediction",
        "bert_confidence",
    ):
        op.drop_column("predictions", col)


def downgrade() -> None:
    # Re-add the legacy columns as nullable so existing rows stay valid.
    for col, typ in (
        ("bert_confidence", sa.Float()),
        ("bert_prediction", sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel")),
        ("naive_bayes_confidence", sa.Float()),
        ("naive_bayes_prediction", sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel")),
        ("random_forest_confidence", sa.Float()),
        ("random_forest_prediction", sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel")),
        ("svm_confidence", sa.Float()),
        ("svm_prediction", sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel")),
    ):
        op.add_column("predictions", sa.Column(col, typ, nullable=True))