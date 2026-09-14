"""widen MySQL algorithm ENUMs with the two new ensemble members

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-14

Migration 0010 aligned the MySQL ENUM columns with the ORM enum member
names, but the ensemble registry has since been restructured: the two new
approved ensembles were added to TrainingAlgorithm / AlgorithmName —

    ENSEMBLE_TFIDF_XLM    = "XGBoost (TF-IDF) + XLM-RoBERTa"
    ENSEMBLE_AVERAGE_ALL  = "Average (All Models)"

The MySQL ``training_history.algorithm`` and ``predictions.algorithm_used``
ENUM columns do not contain those member names yet, so importing training
results (or predicting with the new ensembles) fails with:

    (pymysql.err.DataError) (1265, "Data truncated for column 'algorithm' ...")

This migration widens both columns to the full current member-name lists.
It is a pure DDL widening — no data rewriting is needed because both
member names are new, so no existing rows can reference them.

SQLite development databases are skipped: they store unconstrained
VARCHARs created from the models.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# app.models.training_history.TrainingAlgorithm — full member-name list,
# definition order, LEGACY_XGBOOST omitted (value alias of XGBOOST).
TRAINING_ALGORITHMS = (
    "SVM",
    "RANDOM_FOREST",
    "NAIVE_BAYES",
    "BERT",
    "XGBOOST",
    "XGBOOST_TFDF",
    "MDEBERTA",
    "XLM_ROBERTA",
    "DEBERTA",
    "ROBERTA",
    "ENSEMBLE",
    "ENSEMBLE_XGB_DEBERTA",
    "ENSEMBLE_DEBERTA_ROBERTA",
    "ENSEMBLE_ROBERTA_XGB",
    "ENSEMBLE_XGB_DEBERTA_ROBERTA",
    "ENSEMBLE_TFDF_MDEBERTA",
    "ENSEMBLE_MDEBERTA_XLM",
    "ENSEMBLE_XLM_TFDF",
    "ENSEMBLE_TFDF_MDEBERTA_XLM",
    "ENSEMBLE_TFIDF_XLM",
    "ENSEMBLE_AVERAGE_ALL",
)

# app.models.prediction.AlgorithmName — full member-name list, definition
# order, LEGACY_XGBOOST omitted (value alias of XGBOOST).
ALGORITHM_NAMES = (
    "XGBOOST",
    "XGBOOST_TFDF",
    "MDEBERTA",
    "XLM_ROBERTA",
    "DEBERTA",
    "ROBERTA",
    "LEGACY_ENSEMBLE_SOFT_VOTE",
    "ENSEMBLE_XGB_DEBERTA",
    "ENSEMBLE_DEBERTA_ROBERTA",
    "ENSEMBLE_ROBERTA_XGB",
    "ENSEMBLE_XGB_DEBERTA_ROBERTA",
    "ENSEMBLE_TFDF_MDEBERTA",
    "ENSEMBLE_MDEBERTA_XLM",
    "ENSEMBLE_XLM_TFDF",
    "ENSEMBLE_TFDF_MDEBERTA_XLM",
    "ENSEMBLE_TFIDF_XLM",
    "ENSEMBLE_AVERAGE_ALL",
)


def _enum_literal(values: Sequence[str]) -> str:
    """Render a MySQL ENUM(...) literal from the given member names."""
    return "ENUM(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        # Development SQLite databases store unconstrained VARCHARs created
        # from the models — already compatible with the new member names.
        return

    bind.execute(
        text(
            "ALTER TABLE training_history MODIFY COLUMN algorithm "
            f"{_enum_literal(TRAINING_ALGORITHMS)} NOT NULL"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE predictions "
            f"MODIFY COLUMN algorithm_used {_enum_literal(ALGORITHM_NAMES)} NOT NULL"
        )
    )


def downgrade() -> None:
    """Narrow the ENUMs back to the 0010 lists.

    Only safe when no rows use the two new members; they must be removed
    first, otherwise MySQL refuses the narrowing with the same 1265 error.
    """
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        return

    bind.execute(
        text("DELETE FROM training_history WHERE algorithm IN ('ENSEMBLE_TFIDF_XLM', 'ENSEMBLE_AVERAGE_ALL')")
    )
    bind.execute(
        text("DELETE FROM predictions WHERE algorithm_used IN ('ENSEMBLE_TFIDF_XLM', 'ENSEMBLE_AVERAGE_ALL')")
    )

    old_training = tuple(v for v in TRAINING_ALGORITHMS if v not in ("ENSEMBLE_TFIDF_XLM", "ENSEMBLE_AVERAGE_ALL"))
    old_names = tuple(v for v in ALGORITHM_NAMES if v not in ("ENSEMBLE_TFIDF_XLM", "ENSEMBLE_AVERAGE_ALL"))

    bind.execute(
        text(
            "ALTER TABLE training_history MODIFY COLUMN algorithm "
            f"{_enum_literal(old_training)} NOT NULL"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE predictions "
            f"MODIFY COLUMN algorithm_used {_enum_literal(old_names)} NOT NULL"
        )
    )
