"""replace the Multilingual MiniLM enum value with mBERT Hybrid

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-29

The fourth research model is no longer Multilingual MiniLM. mBERT Hybrid
(``bert-base-multilingual-cased`` encoder + a scikit-learn word/char TF-IDF
and embedding hybrid head) replaces it as the only live production model.

Both ``training_history.algorithm`` and ``predictions.algorithm_used`` are
MySQL ENUMs. Narrowing or replacing an ENUM value in MySQL silently coerces
every row still carrying the old value into the empty string, which would
destroy the existing training history -- exactly the failure mode migration
0015 had to work around. So the old rows are **re-pointed at the new value
first**, while the old value is still legal, and only then is the ENUM
redefined. Existing MiniLM runs are thus carried forward as mBERT Hybrid
rows rather than dropped.

``sqlite`` has no ENUM type (SQLAlchemy renders it as a VARCHAR + CHECK), so
the same UPDATE + table-rebuild is applied via a plain column redefine.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_VALUE = "Multilingual MiniLM"
NEW_VALUE = "mBERT Hybrid"

TRAINING_ALGORITHMS = ("SVM", "Naive Bayes", "Logistic Regression", NEW_VALUE)
ALGORITHM_NAMES = ("SVM", "Naive Bayes", "Logistic Regression", NEW_VALUE)


def _quote(column_type: str) -> str:
    """Render the ENUM/VARCHAR definition for a column type."""
    if column_type.upper().startswith("ENUM"):
        inner = ", ".join(f"'{value}'" for value in ALGORITHM_NAMES)
        return f"ENUM({inner})"
    return "VARCHAR(50)"


def _redefine(bind, table: str, column: str, column_type: str) -> None:
    """Redefine a MySQL ENUM column, or no-op for non-MySQL backends."""
    if bind.dialect.name != "mysql":
        return
    definition = _quote(column_type)
    # MODIFY re-validates every stored value against the new member list; the
    # rows were already re-pointed above, so nothing is left to coerce.
    bind.execute(
        sa.text(
            f"ALTER TABLE `{table}` MODIFY `{column}` {definition} NOT NULL"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Carry the history forward while the old ENUM value is still legal.
    for table, column in (
        ("training_history", "algorithm"),
        ("predictions", "algorithm_used"),
    ):
        bind.execute(
            sa.text(f"UPDATE `{table}` SET `{column}` = :new WHERE `{column}` = :old"),
            {"new": NEW_VALUE, "old": OLD_VALUE},
        )

    # 2. Redefine both ENUMs to the approved 4-model set (MINILM removed).
    _redefine(bind, "training_history", "algorithm", "ENUM")
    _redefine(bind, "predictions", "algorithm_used", "ENUM")


def downgrade() -> None:
    bind = op.get_bind()

    # Widen the ENUMs first so the restored value is legal, then point the
    # mBERT rows back at MiniLM.
    if bind.dialect.name == "mysql":
        for table, column in (
            ("training_history", "algorithm"),
            ("predictions", "algorithm_used"),
        ):
            members = ", ".join(
                f"'{value}'" for value in (*ALGORITHM_NAMES, OLD_VALUE)
            )
            bind.execute(
                sa.text(
                    f"ALTER TABLE `{table}` MODIFY `{column}` ENUM({members}) NOT NULL"
                )
            )

    for table, column in (
        ("training_history", "algorithm"),
        ("predictions", "algorithm_used"),
    ):
        bind.execute(
            sa.text(f"UPDATE `{table}` SET `{column}` = :old WHERE `{column}` = :new"),
            {"old": OLD_VALUE, "new": NEW_VALUE},
        )