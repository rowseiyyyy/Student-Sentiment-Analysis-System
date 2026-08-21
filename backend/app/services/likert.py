"""Deterministic scoring for Likert-scale (1-5) evaluation questions.

This is intentionally NOT part of the text sentiment pipeline. Likert
responses are numeric ratings, not free text, and must never be
paraphrased into a sentence and run through XGBoost/DeBERTa/RoBERTa.
Classification here is a simple, reproducible numerical aggregation so
results are always explainable from the raw scores.

Thresholds are configurable but default to the standard 1-5 midpoint
split used across the rest of the project's documentation:
    average >= POSITIVE_THRESHOLD -> Positive
    average <= NEGATIVE_THRESHOLD -> Negative
    otherwise                     -> Neutral
"""
from __future__ import annotations

from typing import Any

POSITIVE_THRESHOLD = 3.5
NEGATIVE_THRESHOLD = 2.5

MIN_SCALE_VALUE = 1
MAX_SCALE_VALUE = 5


def classify_likert(
    ratings: dict[str, Any],
    positive_threshold: float = POSITIVE_THRESHOLD,
    negative_threshold: float = NEGATIVE_THRESHOLD,
) -> tuple[str, float]:
    """Classify a set of 1-5 Likert ratings into Positive/Neutral/Negative.

    Parameters
    ----------
    ratings : dict[str, Any]
        Mapping of question/aspect name -> numeric score (1-5).

    Returns
    -------
    tuple[str, float]
        ``(label, average_score)`` where ``label`` is one of
        "Positive", "Neutral", "Negative".

    Raises
    ------
    ValueError
        If ``ratings`` is empty or contains a non-numeric / out-of-range
        value.
    """
    if not ratings:
        raise ValueError("ratings must be a non-empty mapping of question -> 1-5 score.")

    values: list[float] = []
    for key, raw_value in ratings.items():
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Rating for '{key}' is not numeric: {raw_value!r}") from exc
        if not (MIN_SCALE_VALUE <= value <= MAX_SCALE_VALUE):
            raise ValueError(
                f"Rating for '{key}' must be between {MIN_SCALE_VALUE} and {MAX_SCALE_VALUE}, got {value}."
            )
        values.append(value)

    average = sum(values) / len(values)

    if average >= positive_threshold:
        label = "Positive"
    elif average <= negative_threshold:
        label = "Negative"
    else:
        label = "Neutral"

    return label, average