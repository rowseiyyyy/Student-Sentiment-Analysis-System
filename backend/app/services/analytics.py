"""
Analytics aggregation service backing the dashboard endpoints.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction, SentimentLabel
from app.services.preprocessing import STOPWORDS


def _breakdown(
    db: Session,
    category: Optional[EvaluationCategory] = None,
    days: Optional[int] = None,
) -> dict:
    query = db.query(Prediction.official_prediction, func.count(Prediction.id)).join(
        Evaluation, Evaluation.id == Prediction.evaluation_id
    )
    if category is not None:
        query = query.filter(Evaluation.category == category)
    if days is not None:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(Evaluation.created_at >= cutoff)
    query = query.group_by(Prediction.official_prediction)

    counts = {SentimentLabel.POSITIVE: 0, SentimentLabel.NEUTRAL: 0, SentimentLabel.NEGATIVE: 0}
    for label, count in query.all():
        counts[label] = count

    total = sum(counts.values())
    pct = lambda n: round((n / total) * 100, 2) if total else 0.0  # noqa: E731

    return {
        "positive": counts[SentimentLabel.POSITIVE],
        "neutral": counts[SentimentLabel.NEUTRAL],
        "negative": counts[SentimentLabel.NEGATIVE],
        "total": total,
        "positive_pct": pct(counts[SentimentLabel.POSITIVE]),
        "neutral_pct": pct(counts[SentimentLabel.NEUTRAL]),
        "negative_pct": pct(counts[SentimentLabel.NEGATIVE]),
    }


def overall_analytics(
    db: Session,
    category: Optional[EvaluationCategory] = None,
    days: Optional[int] = None,
) -> dict:
    breakdown = _breakdown(db, category=category, days=days)
    conf_query = db.query(func.avg(Prediction.confidence_score)).join(
        Evaluation, Evaluation.id == Prediction.evaluation_id
    )
    vol_query = db.query(func.count(Evaluation.id)).join(
        Prediction, Prediction.evaluation_id == Evaluation.id
    )
    if category is not None:
        conf_query = conf_query.filter(Evaluation.category == category)
        vol_query = vol_query.filter(Evaluation.category == category)
    if days is not None:
        cutoff = datetime.utcnow() - timedelta(days=days)
        conf_query = conf_query.filter(Evaluation.created_at >= cutoff)
        vol_query = vol_query.filter(Evaluation.created_at >= cutoff)
    avg_conf = conf_query.scalar() or 0.0
    # Count only evaluations that have a corresponding prediction record,
    # matching the inner join used in _breakdown() to avoid inflated counts
    volume = vol_query.scalar() or 0
    return {
        "breakdown": breakdown,
        "average_confidence": round(float(avg_conf), 4),
        "evaluation_volume": volume,
    }


def category_analytics(
    db: Session,
    category: EvaluationCategory,
    days: Optional[int] = None,
) -> dict:
    breakdown = _breakdown(db, category=category, days=days)
    conf_query = (
        db.query(func.avg(Prediction.confidence_score))
        .join(Evaluation, Evaluation.id == Prediction.evaluation_id)
        .filter(Evaluation.category == category)
    )
    if days is not None:
        conf_query = conf_query.filter(Evaluation.created_at >= datetime.utcnow() - timedelta(days=days))
    avg_conf = conf_query.scalar() or 0.0
    return {
        "category": category.value,
        "breakdown": breakdown,
        "average_confidence": round(float(avg_conf), 4),
    }


def trend_analytics(
    db: Session,
    granularity: str = "monthly",
    days: Optional[int] = None,
    category: Optional[EvaluationCategory] = None,
) -> dict:
    fmt = "%Y-%m" if granularity == "monthly" else "%Y-%m-%d"

    query = db.query(Evaluation.created_at, Prediction.official_prediction).join(
        Prediction, Prediction.evaluation_id == Evaluation.id
    )
    if category is not None:
        query = query.filter(Evaluation.category == category)
    if days is not None:
        query = query.filter(Evaluation.created_at >= datetime.utcnow() - timedelta(days=days))
    rows = query.all()

    buckets: dict[str, Counter] = {}
    for created_at, label in rows:
        key = created_at.strftime(fmt)
        buckets.setdefault(key, Counter())[label] += 1

    points = []
    for period in sorted(buckets.keys()):
        counter = buckets[period]
        total = sum(counter.values())
        points.append({
            "period": period,
            "positive": counter.get(SentimentLabel.POSITIVE, 0),
            "neutral": counter.get(SentimentLabel.NEUTRAL, 0),
            "negative": counter.get(SentimentLabel.NEGATIVE, 0),
            "total": total,
        })

    return {"granularity": granularity, "points": points}


_WORD_PATTERN = re.compile(r"[a-zA-Z']+")


def word_frequency(db: Session, sentiment: SentimentLabel, top_n: int = 30) -> dict:
    rows = (
        db.query(Evaluation.comment)
        .join(Prediction, Prediction.evaluation_id == Evaluation.id)
        .filter(Prediction.official_prediction == sentiment)
        .all()
    )

    counter: Counter = Counter()
    for (comment,) in rows:
        words = [w.lower() for w in _WORD_PATTERN.findall(comment or "")]
        words = [w for w in words if w not in STOPWORDS and len(w) > 2]
        counter.update(words)

    top_words = [{"word": w, "count": c} for w, c in counter.most_common(top_n)]
    return {"sentiment": sentiment.value, "words": top_words}


def top_comments(db: Session, kind: str, limit: int = 10) -> dict:
    """kind='complaints' -> highest-confidence, purely Negative comments.
    kind='appreciations' -> highest-confidence, purely Positive comments.

    "Purely" means the comment's ML sentiment is NOT contradicted by the
    same submission's Likert rating (Evaluation.is_mismatch is False).
    A comment whose text reads negative but whose Likert score reads
    positive (or vice versa) is a mixed signal, not a clean complaint or
    appreciation, so it's excluded here even if its text-sentiment
    confidence is high. See app.services.mismatch for how is_mismatch is
    derived.
    """
    target = SentimentLabel.NEGATIVE if kind == "complaints" else SentimentLabel.POSITIVE

    rows = (
        db.query(Evaluation, Prediction)
        .join(Prediction, Prediction.evaluation_id == Evaluation.id)
        .filter(Prediction.official_prediction == target)
        .filter(Evaluation.is_mismatch.is_(False))
        .order_by(Prediction.confidence_score.desc())
        .limit(limit)
        .all()
    )

    items = [
        {
            "evaluation_id": ev.id,
            "category": ev.category.value,
            "comment": ev.comment,
            "confidence": pred.confidence_score,
        }
        for ev, pred in rows
    ]
    return {"kind": kind, "items": items}