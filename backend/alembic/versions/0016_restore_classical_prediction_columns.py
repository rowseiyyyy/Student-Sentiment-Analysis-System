"""restore classical research prediction columns, drop retired model columns

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-21

The approved research set is SVM, Naive Bayes, Logistic Regression and
Multilingual MiniLM. Migration 0009 dropped the classical per-model columns
from ``predictions`` (svm / random_forest / naive_bayes / bert) when the
retired XGBoost + DeBERTa + RoBERTa pipeline replaced them, and 0005 added
``xgb_*`` / ``deberta_*`` / ``roberta_*`` in their place.

The ORM now maps that classical research set again
(``app/models/prediction.py``: ``svm_prediction``, ``svm_confidence``,
``naive_bayes_prediction``, ``naive_bayes_confidence``,
``logistic_regression_prediction``, ``logistic_regression_confidence``), so
every query selecting ``Prediction`` failed against MySQL with:

    (pymysql.err.OperationalError) (1054, "Unknown column
    'predictions.svm_prediction' in 'field list'")

This migration restores the six classical columns (nullable — they stay NULL
for live traffic, since only MiniLM runs in the request path) and drops the
six retired ``xgb_*`` / ``deberta_*`` / ``roberta_*`` columns, which no code
references any more.

Both directions are guarded by ``information_schema`` lookups, so the
migration is idempotent against databases that were hand-patched or
partially drifted.

SQLite development databases are skipped: they are created from the models
via ``Base.metadata.create_all()`` and already match the ORM.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# app.models.prediction.SentimentLabel — member names, definition order.
SENTIMENT_LABELS = ("POSITIVE", "NEUTRAL", "NEGATIVE")


def _enum_body() -> str:
    """Render the MySQL ENUM(...) body (without the ``ENUM`` keyword)."""
    return ", ".join(f"'{value}'" for value in SENTIMENT_LABELS)


SENTIMENT_ENUM = f"ENUM({_enum_body()})"


# (column, column definition, position clause) in ORM declaration order, so the
# resulting table layout matches app/models/prediction.py.
CLASSICAL_COLUMNS = (
    ("svm_prediction", f"{SENTIMENT_ENUM} NULL", "AFTER `evaluation_id`"),
    ("svm_confidence", "FLOAT NULL", "AFTER `svm_prediction`"),
    ("naive_bayes_prediction", f"{SENTIMENT_ENUM} NULL", "AFTER `svm_confidence`"),
    ("naive_bayes_confidence", "FLOAT NULL", "AFTER `naive_bayes_prediction`"),
    (
        "logistic_regression_prediction",
        f"{SENTIMENT_ENUM} NULL",
        "AFTER `naive_bayes_confidence`",
    ),
    (
        "logistic_regression_confidence",
        "FLOAT NULL",
        "AFTER `logistic_regression_prediction`",
    ),
)

# Columns added by 0005 for the retired XGBoost / DeBERTa / RoBERTa pipeline.
RETIRED_COLUMNS = (
    "xgb_prediction",
    "xgb_confidence",
    "deberta_prediction",
    "deberta_confidence",
    "roberta_prediction",
    "roberta_confidence",
)


def _column_types(bind, table: str) -> dict[str, str]:
    """Map column name -> normalised MySQL COLUMN_TYPE for ``table``.

    Read from ``information_schema`` because it reports the exact stored
    definition (e.g. ``enum('POSITIVE','NEUTRAL','NEGATIVE')``) that the
    reflection layer would otherwise have to be string-matched against.
    """
    rows = bind.execute(
        text(
            "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
        ),
        {"table": table},
    )
    return {name: _normalise(value) for name, value in rows}


def _normalise(column_type: str) -> str:
    """Lowercase and strip whitespace so definitions compare reliably."""
    return "".join(str(column_type).split()).lower()


# Canonical stored definition of the sentiment ENUM, normalised the same way
# as _column_types() so the comparison below is reliable.
ENUM_TARGET = _normalise(f"ENUM({_enum_body()})")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        return

    existing = _column_types(bind, "predictions")

    for column, definition, position in CLASSICAL_COLUMNS:
        if column not in existing:
            op.execute(f"ALTER TABLE predictions ADD COLUMN `{column}` {definition} {position}")
            continue

        # The column already exists — normalise it instead of skipping, so a
        # database restored from the 0009 downgrade (which re-created these as
        # the value-form ENUM('Positive','Neutral','Negative')) ends up
        # readable by the ORM's name-form Enum. MySQL's case-insensitive
        # collation maps an existing 'Positive' onto the 'POSITIVE' member, so
        # the MODIFY converts rather than truncates.
        if _normalise(definition).startswith("enum(") and existing[column] != ENUM_TARGET:
            op.execute(f"ALTER TABLE predictions MODIFY COLUMN `{column}` ENUM({_enum_body()}) NULL")

    for column in RETIRED_COLUMNS:
        if column not in existing:
            continue
        op.execute(f"ALTER TABLE predictions DROP COLUMN `{column}`")


def downgrade() -> None:
    """Restore the retired columns and remove the classical research columns.

    Column contents cannot be restored — the data in the dropped columns is
    gone once ``upgrade`` runs.
    """
    bind = op.get_bind()
    if bind.engine.name != "mysql":
        return

    existing = _column_types(bind, "predictions")

    for column in RETIRED_COLUMNS:
        if column in existing:
            continue
        if column.endswith("_prediction"):
            definition = f"{SENTIMENT_ENUM} NULL"
        else:
            definition = "FLOAT NULL"
        op.execute(f"ALTER TABLE predictions ADD COLUMN `{column}` {definition}")

    for column, _definition, _position in CLASSICAL_COLUMNS:
        if column not in existing:
            continue
        op.execute(f"ALTER TABLE predictions DROP COLUMN `{column}`")
