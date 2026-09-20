"""replace retired transformer/xgboost algorithm ENUMs with the 4-model set

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-20

The approved research model set is now SVM, Naive Bayes, Logistic
Regression and Multilingual MiniLM. This migration rewrites the
``training_history.algorithm`` and ``predictions.algorithm_used`` MySQL
ENUM columns to the new member names (SVM, NAIVE_BAYES,
LOGISTIC_REGRESSION, MINILM) and rewrites any rows still carrying a
retired legacy value (XGBoost / mDeBERTa / XLM-RoBERTa / ensembles) to
MINILM research rows are re-trainable; production rows stay production.

MySQL ENUM semantics: a value outside the new ENUM would be truncated to
'' on MODIFY, so legacy values must be mapped BEFORE the column type is
narrowed.

SQLite development databases are skipped: they store unconstrained
VARCHARs created from the models.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# app.models.training_history.TrainingAlgorithm — member names, definition order.
TRAINING_ALGORITHMS = (
    "SVM",
    "NAIVE_BAYES",
    "LOGISTIC_REGRESSION",
    "MINILM",
)

# app.models.prediction.AlgorithmName — member names, definition order.
ALGORITHM_NAMES = (
    "SVM",
    "NAIVE_BAYES",
    "LOGISTIC_REGRESSION",
    "MINILM",
)

# Legacy member names (every enum value that existed before this change).
LEGACY_MEMBERS = (
    "RANDOM_FOREST",
    "BERT",
    "XGBOOST",
    "XGBOOST_TFDF",
    "MDEBERTA",
    "XLM_ROBERTA",
    "DEBERTA",
    "ROBERTA",
    "ENSEMBLE",
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


def _legacy_sql_list() -> str:
    return "(" + ", ".join(f"'{value}'" for value in LEGACY_MEMBERS) + ")"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        return

    # Map retired legacy rows to MINILM BEFORE narrowing the ENUM, so no
    # value is truncated to ''. (SQLite stores plain VARCHARs: untouched.)
    bind.execute(
        text(
            f"UPDATE training_history SET algorithm = 'MINILM' "
            f"WHERE algorithm IN {_legacy_sql_list()}"
        )
    )
    bind.execute(
        text(
            f"UPDATE predictions SET algorithm_used = 'MINILM' "
            f"WHERE algorithm_used IN {_legacy_sql_list()}"
        )
    )

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
    """Narrow back to the pre-0015 lists (legacy values cannot be restored)."""
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        return

    bind.execute(
        text(
            "ALTER TABLE training_history MODIFY COLUMN algorithm "
            "ENUM('SVM','RANDOM_FOREST','NAIVE_BAYES','BERT','XGBOOST',"
            "'XGBOOST_TFDF','MDEBERTA','XLM_ROBERTA','MINILM','DEBERTA',"
            "'ROBERTA','ENSEMBLE','ENSEMBLE_XGB_DEBERTA',"
            "'ENSEMBLE_DEBERTA_ROBERTA','ENSEMBLE_ROBERTA_XGB',"
            "'ENSEMBLE_XGB_DEBERTA_ROBERTA','ENSEMBLE_TFDF_MDEBERTA',"
            "'ENSEMBLE_MDEBERTA_XLM','ENSEMBLE_XLM_TFDF',"
            "'ENSEMBLE_TFDF_MDEBERTA_XLM','ENSEMBLE_TFIDF_XLM',"
            "'ENSEMBLE_AVERAGE_ALL') NOT NULL"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE predictions MODIFY COLUMN algorithm_used "
            "ENUM('XGBOOST','XGBOOST_TFDF','MDEBERTA','XLM_ROBERTA','MINILM',"
            "'DEBERTA','ROBERTA','LEGACY_ENSEMBLE_SOFT_VOTE',"
            "'ENSEMBLE_XGB_DEBERTA','ENSEMBLE_DEBERTA_ROBERTA',"
            "'ENSEMBLE_ROBERTA_XGB','ENSEMBLE_XGB_DEBERTA_ROBERTA',"
            "'ENSEMBLE_TFDF_MDEBERTA','ENSEMBLE_MDEBERTA_XLM',"
            "'ENSEMBLE_XLM_TFDF','ENSEMBLE_TFDF_MDEBERTA_XLM',"
            "'ENSEMBLE_TFIDF_XLM','ENSEMBLE_AVERAGE_ALL') NOT NULL"
        )
    )
