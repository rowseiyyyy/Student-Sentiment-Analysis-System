"""Approved model registry and shared label ordering.

The approved research model set is:
    1. SVM (TF-IDF)
    2. Naive Bayes (TF-IDF)
    3. Logistic Regression (TF-IDF)
    4. Multilingual MiniLM  (the ONLY live production model)

Ensembles were retired — the registry now contains single models only. The
``CLASS_ORDER`` constant is shared by every model service, training and the
prediction pipeline so labels always align.
"""
from __future__ import annotations

# Canonical label ordering shared by every model service, training and the
# prediction pipeline.
CLASS_ORDER = ("Negative", "Neutral", "Positive")

# Approved single-model approaches.
SINGLE_MODELS: tuple[str, ...] = (
    "SVM",
    "Naive Bayes",
    "Logistic Regression",
    "Multilingual MiniLM",
)

# Complete approved approach set (no ensembles remain).
APPROVED_APPROACHES: tuple[str, ...] = SINGLE_MODELS

# Retired: no ensembles are approved anymore. Kept as empty structures so
# legacy imports stay import-safe.
ENSEMBLES: dict[str, list[str]] = {}
EQUAL_WEIGHT_ENSEMBLES: frozenset[str] = frozenset()


def members_of(ensemble_name: str) -> list[str]:
    """Return the ordered participating model keys for an ensemble.

    Ensembles are retired, so this always returns an empty list."""
    return list(ENSEMBLES.get(ensemble_name, []))


def normalize_weights(members: list[str], weights: dict[str, float]) -> dict[str, float]:
    """Return equal weights summing to one over ``members`` (ensembles are
    retired, so only the degenerate equal-weight case remains)."""
    if not members:
        raise ValueError("Cannot normalise weights for an empty member list.")
    equal = 1.0 / len(members)
    return {member: equal for member in members}

