"""align MySQL ENUM columns with ORM enum member names

Revision ID: 0010
Revises: 8ed741be7f17
Create Date: 2026-09-11

The ORM models declare str-based Python enums (TrainingAlgorithm,
TrainingStatus, AlgorithmName, SentimentLabel, EvaluationCategory, UserRole)
and SQLAlchemy persists the member *name* (e.g. 'XGBOOST_TFDF', 'RUNNING',
'POSITIVE'). The MySQL tables, however, were created by migrations 0001/0003
with the enum *values* (e.g. 'XGBoost (TF-DF)', 'running', 'Positive'), so
every ORM insert into an enum-backed column failed with:

    (pymysql.err.DataError) (1265, "Data truncated for column 'algorithm' at row 1")

This migration rewrites any value-form rows to the name-form the ORM reads
and writes, then widens every affected ENUM column to exactly the member-name
list SQLAlchemy generates on MySQL. Value aliases that share a value with
another member (LEGACY_XGBOOST) are intentionally absent from the lists —
SQLAlchemy omits them from its own DDL as well (omit_aliases=True).

SQLite development databases are skipped: they are created from the models
via Base.metadata.create_all() and already store name-form strings
(unconstrained VARCHAR), matching this migration's end state.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0010"
down_revision: Union[str, None] = "8ed741be7f17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# app.models.training_history.TrainingAlgorithm — member names, definition
# order, LEGACY_XGBOOST omitted (value alias of XGBOOST).
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
)

# app.models.training_history.TrainingStatus
TRAINING_STATUSES = ("RUNNING", "COMPLETED", "FAILED")

# app.models.prediction.AlgorithmName — member names, definition order,
# LEGACY_XGBOOST omitted (value alias of XGBOOST).
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
)

# app.models.prediction.SentimentLabel
SENTIMENT_LABELS = ("POSITIVE", "NEUTRAL", "NEGATIVE")

# app.models.evaluation.EvaluationCategory
EVALUATION_CATEGORIES = ("PROFESSOR", "STAFF", "PAYMENTS", "FACILITIES")

# app.models.user.UserRole
USER_ROLES = ("STUDENT", "ADMINISTRATOR", "FACULTY")


def _enum_literal(values: Sequence[str]) -> str:
    """Render a MySQL ENUM(...) literal from the given member names."""
    return "ENUM(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        # Development SQLite databases are created from the models directly
        # and already store name-form strings; nothing to do.
        return

    # ------------------------------------------------------------------
    # training_history — convert any legacy value-form rows to name-form
    # *before* widening the ENUM, or the ALTER would truncate them.
    # ------------------------------------------------------------------
    bind.execute(text("UPDATE training_history SET algorithm = 'RANDOM_FOREST' WHERE algorithm = 'Random Forest'"))
    bind.execute(text("UPDATE training_history SET algorithm = 'NAIVE_BAYES' WHERE algorithm = 'Naive Bayes'"))
    bind.execute(text("UPDATE training_history SET status = 'RUNNING' WHERE status = 'running'"))
    bind.execute(text("UPDATE training_history SET status = 'COMPLETED' WHERE status = 'completed'"))
    bind.execute(text("UPDATE training_history SET status = 'FAILED' WHERE status = 'failed'"))
    bind.execute(
        text(
            f"ALTER TABLE training_history MODIFY COLUMN algorithm "
            f"{_enum_literal(TRAINING_ALGORITHMS)} NOT NULL"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE training_history "
            f"MODIFY COLUMN status {_enum_literal(TRAINING_STATUSES)} "
            "NOT NULL DEFAULT 'RUNNING'"
        )
    )
    # ------------------------------------------------------------------
    # predictions — sentiment columns convert cleanly; algorithm_used does
    # not: the legacy algorithms ('SVM', 'Random Forest', 'Naive Bayes',
    # 'BERT') have no AlgorithmName members anymore, so rows carrying them
    # are already unreadable through the ORM (same stance as migration 0009)
    # and would poison any SELECT over the table. Drop them, then widen.
    # ------------------------------------------------------------------
    bind.execute(text("UPDATE predictions SET official_prediction = 'POSITIVE' WHERE official_prediction = 'Positive'"))
    bind.execute(text("UPDATE predictions SET official_prediction = 'NEUTRAL' WHERE official_prediction = 'Neutral'"))
    bind.execute(text("UPDATE predictions SET official_prediction = 'NEGATIVE' WHERE official_prediction = 'Negative'"))
    bind.execute(text("UPDATE predictions SET xgb_prediction = 'POSITIVE' WHERE xgb_prediction = 'Positive'"))
    bind.execute(text("UPDATE predictions SET xgb_prediction = 'NEUTRAL' WHERE xgb_prediction = 'Neutral'"))
    bind.execute(text("UPDATE predictions SET xgb_prediction = 'NEGATIVE' WHERE xgb_prediction = 'Negative'"))
    bind.execute(text("UPDATE predictions SET deberta_prediction = 'POSITIVE' WHERE deberta_prediction = 'Positive'"))
    bind.execute(text("UPDATE predictions SET deberta_prediction = 'NEUTRAL' WHERE deberta_prediction = 'Neutral'"))
    bind.execute(text("UPDATE predictions SET deberta_prediction = 'NEGATIVE' WHERE deberta_prediction = 'Negative'"))
    bind.execute(text("UPDATE predictions SET roberta_prediction = 'POSITIVE' WHERE roberta_prediction = 'Positive'"))
    bind.execute(text("UPDATE predictions SET roberta_prediction = 'NEUTRAL' WHERE roberta_prediction = 'Neutral'"))
    bind.execute(text("UPDATE predictions SET roberta_prediction = 'NEGATIVE' WHERE roberta_prediction = 'Negative'"))
    bind.execute(
        text(
            "DELETE FROM predictions WHERE algorithm_used IN "
            "('SVM', 'Random Forest', 'Naive Bayes', 'BERT')"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE predictions "
            f"MODIFY COLUMN official_prediction {_enum_literal(SENTIMENT_LABELS)} NOT NULL"
        )
    )
    for column in ("xgb_prediction", "deberta_prediction", "roberta_prediction"):
        bind.execute(
            text(
                f"ALTER TABLE predictions MODIFY COLUMN {column} "
                f"{_enum_literal(SENTIMENT_LABELS)} NULL"
            )
        )
    bind.execute(
        text(
            "ALTER TABLE predictions "
            f"MODIFY COLUMN algorithm_used {_enum_literal(ALGORITHM_NAMES)} NOT NULL"
        )
    )


    # ------------------------------------------------------------------
    # users — note the original 0001 ENUM omitted 'faculty' entirely even
    # though UserRole.FACULTY exists; the widened list fixes that too.
    # ------------------------------------------------------------------
    bind.execute(text("UPDATE users SET role = 'STUDENT' WHERE role = 'student'"))
    bind.execute(text("UPDATE users SET role = 'ADMINISTRATOR' WHERE role = 'administrator'"))
    bind.execute(text("UPDATE users SET role = 'FACULTY' WHERE role = 'faculty'"))
    bind.execute(
        text(
            "ALTER TABLE users "
            f"MODIFY COLUMN role {_enum_literal(USER_ROLES)} NOT NULL"
        )
    )

    # ------------------------------------------------------------------
    # evaluations — 0001 used 'Faculty'/'Payment' while the enum's values
    # are 'Professors'/'Payments'; map every historical spelling to the
    # member name the ORM persists.
    # ------------------------------------------------------------------
    bind.execute(text("UPDATE evaluations SET category = 'PROFESSOR' WHERE category IN ('Faculty', 'Professors')"))
    bind.execute(text("UPDATE evaluations SET category = 'PAYMENTS' WHERE category IN ('Payment', 'Payments')"))
    bind.execute(text("UPDATE evaluations SET category = 'STAFF' WHERE category = 'Staff'"))
    bind.execute(text("UPDATE evaluations SET category = 'FACILITIES' WHERE category = 'Facilities'"))
    bind.execute(
        text(
            "ALTER TABLE evaluations "
            f"MODIFY COLUMN category {_enum_literal(EVALUATION_CATEGORIES)} NOT NULL"
        )
    )


def downgrade() -> None:
    """Best-effort restore of the value-form ENUMs from 0001/0003.

    Rows written after this migration carry member names that have no
    value-form counterpart (e.g. 'XGBOOST_TFDF'); convert what is
    reversible first, mirroring migration 0003's approach.
    """
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        return

    bind.execute(text("UPDATE training_history SET algorithm = 'Random Forest' WHERE algorithm = 'RANDOM_FOREST'"))
    bind.execute(text("UPDATE training_history SET algorithm = 'Naive Bayes' WHERE algorithm = 'NAIVE_BAYES'"))
    bind.execute(text("UPDATE training_history SET status = 'running' WHERE status = 'RUNNING'"))
    for column in ("xgb_prediction", "deberta_prediction", "roberta_prediction"):
        bind.execute(
            text(
                f"ALTER TABLE predictions MODIFY COLUMN {column} "
                "ENUM('Positive', 'Neutral', 'Negative') NULL"
            )
        )
    bind.execute(
        text(
            "ALTER TABLE predictions MODIFY COLUMN official_prediction "
            "ENUM('Positive', 'Neutral', 'Negative') NOT NULL"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE predictions MODIFY COLUMN algorithm_used "
            "ENUM('SVM', 'Random Forest', 'Naive Bayes', 'BERT') NOT NULL"
        )
    )

    bind.execute(
        text(
            "ALTER TABLE users MODIFY COLUMN role "
            "ENUM('student', 'administrator') NOT NULL"
        )
    )

    bind.execute(
        text(
            "ALTER TABLE evaluations MODIFY COLUMN category "
            "ENUM('Faculty', 'Staff', 'Payment', 'Facilities') NOT NULL"
        )
    )

    bind.execute(text("UPDATE training_history SET status = 'completed' WHERE status = 'COMPLETED'"))
    bind.execute(text("UPDATE training_history SET status = 'failed' WHERE status = 'FAILED'"))
    bind.execute(
        text(
            "ALTER TABLE training_history MODIFY COLUMN algorithm "
            "ENUM('SVM', 'Random Forest', 'Naive Bayes', 'BERT') NOT NULL"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE training_history MODIFY COLUMN status "
            "ENUM('running', 'completed', 'failed') NOT NULL DEFAULT 'running'"
        )
    )

