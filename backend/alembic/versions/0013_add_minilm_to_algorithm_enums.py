"""widen MySQL algorithm ENUMs with Multilingual MiniLM

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-14

The approved research model set was restructured again: Multilingual MiniLM
(paraphrase-multilingual-MiniLM-L12-v2) was added as a fourth single model,
and the ensemble registry was reduced to the single approved ensemble
mDeBERTa + XLM-RoBERTa (the composites widened in 0012 remain as legacy
enum members for historical rows).

This migration adds MINILM to the ``training_history.algorithm`` and
``predictions.algorithm_used`` MySQL ENUM columns. Pure DDL widening —
no data rewriting is needed because the member is new.

SQLite development databases are skipped: they store unconstrained
VARCHARs created from the models.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0013"
down_revision: Union[str, None] = "0012"
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
    "MINILM",
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
    "MINILM",
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
    """Narrow the ENUMs back to the 0012 lists (requires no MINILM rows)."""
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        return

    bind.execute(text("DELETE FROM training_history WHERE algorithm = 'MINILM'"))
    bind.execute(text("DELETE FROM predictions WHERE algorithm_used = 'MINILM'"))

    old_training = tuple(v for v in TRAINING_ALGORITHMS if v != "MINILM")
    old_names = tuple(v for v in ALGORITHM_NAMES if v != "MINILM")

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
