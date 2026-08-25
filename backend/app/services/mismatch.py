"""Likert-vs-sentiment mismatch detection.

Combines a numeric Likert classification (from likert.py) with a text
sentiment classification (from transformer_service.py / xgboost_service.py)
for the *same* category submission, and flags cases where the two
disagree strongly enough to warrant admin review.

This module deliberately does NOT blend the two into a single score.
Likert remains the official per-category rating; sentiment remains a
separate qualitative signal. This only adds a comparison layer on top.
"""
from __future__ import annotations

from enum import Enum
from typing import NamedTuple

# Reuse the same thresholds/labels used elsewhere so "Positive"/"Neutral"/
# "Negative" always mean the same thing whether they came from Likert
# aggregation or ML sentiment classification.
POSITIVE_LABEL = "Positive"
NEUTRAL_LABEL = "Neutral"
NEGATIVE_LABEL = "Negative"


class MismatchType(str, Enum):
    NONE = "none"
    UNEXPECTED_NEGATIVE = "unexpected_negative"  # high Likert, negative comment
    UNEXPECTED_POSITIVE = "unexpected_positive"  # low Likert, positive comment


class MismatchResult(NamedTuple):
    is_mismatch: bool
    mismatch_type: MismatchType
    likert_label: str
    likert_average: float
    sentiment_label: str
    sentiment_confidence: float


def detect_mismatch(
    likert_label: str,
    likert_average: float,
    sentiment_label: str,
    sentiment_confidence: float,
    *,
    confidence_floor: float = 0.55,
) -> MismatchResult:
    """Compare a category's Likert classification against its comment
    sentiment classification and flag disagreement.

    Parameters
    ----------
    likert_label : str
        Output of ``classify_likert(...)`` — "Positive"/"Neutral"/"Negative".
    likert_average : float
        The numeric average returned alongside ``likert_label``.
    sentiment_label : str
        Output of the ML model's ``predict(...)`` — "Positive"/"Neutral"/"Negative".
    sentiment_confidence : float
        Confidence score returned alongside ``sentiment_label``.
    confidence_floor : float
        Below this confidence, we don't flag a mismatch — a low-confidence
        sentiment call disagreeing with Likert is more likely model
        uncertainty than a genuine signal worth surfacing to an admin.

    Returns
    -------
    MismatchResult
        Carries both original labels/scores plus the mismatch verdict, so
        callers can persist or display the full context without
        re-deriving it.

    Notes
    -----
    Mid/Neutral combinations are intentionally never flagged — only a
    genuine high/low vs. opposite-sentiment disagreement counts. This
    keeps the "Needs Review" queue focused on submissions actually worth
    an admin's time, not every minor inconsistency.
    """
    mismatch_type = MismatchType.NONE

    if sentiment_confidence >= confidence_floor:
        if likert_label == POSITIVE_LABEL and sentiment_label == NEGATIVE_LABEL:
            mismatch_type = MismatchType.UNEXPECTED_NEGATIVE
        elif likert_label == NEGATIVE_LABEL and sentiment_label == POSITIVE_LABEL:
            mismatch_type = MismatchType.UNEXPECTED_POSITIVE

    return MismatchResult(
        is_mismatch=mismatch_type is not MismatchType.NONE,
        mismatch_type=mismatch_type,
        likert_label=likert_label,
        likert_average=likert_average,
        sentiment_label=sentiment_label,
        sentiment_confidence=sentiment_confidence,
    )


def summarize_category(
    category: str,
    likert_ratings: dict[str, float],
    comment_text: str,
    *,
    likert_classifier,
    sentiment_predictor,
) -> dict:
    """Convenience wrapper: runs both classifiers and returns the full
    side-by-side payload for one category on one submission, ready to
    attach to a submission record or API response.

    ``likert_classifier`` should be ``likert.classify_likert``.
    ``sentiment_predictor`` should be a bound ``predict`` method from
    ``TransformerSentimentService`` or ``XGBoostService`` (anything
    returning ``(label, confidence, probabilities)``).
    """
    likert_label, likert_average = likert_classifier(likert_ratings)
    sentiment_label, sentiment_confidence, sentiment_probs = sentiment_predictor(comment_text)

    mismatch = detect_mismatch(
        likert_label=likert_label,
        likert_average=likert_average,
        sentiment_label=sentiment_label,
        sentiment_confidence=sentiment_confidence,
    )

    return {
        "category": category,
        "likert": {"label": likert_label, "average": likert_average},
        "sentiment": {
            "label": sentiment_label,
            "confidence": sentiment_confidence,
            "probabilities": sentiment_probs,
        },
        "mismatch": {
            "is_mismatch": mismatch.is_mismatch,
            "type": mismatch.mismatch_type.value,
        },
    }