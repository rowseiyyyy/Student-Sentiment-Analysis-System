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
from app.core.config import settings
from app.core.time import utcnow_naive
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
        cutoff = utcnow_naive() - timedelta(days=days)
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
    # Health-snapshot extras: how many predictions the model was unsure about,
    # and how long the dashboard has been idle. Both follow the same
    # category/date filters as the rest of the Overview tab.
    low_conf_query = (
        db.query(func.count(Prediction.id))
        .join(Evaluation, Evaluation.id == Prediction.evaluation_id)
        .filter(Prediction.confidence_score < settings.LOW_CONFIDENCE_THRESHOLD)
    )
    last_query = db.query(func.max(Evaluation.created_at)).join(
        Prediction, Prediction.evaluation_id == Evaluation.id
    )
    if category is not None:
        conf_query = conf_query.filter(Evaluation.category == category)
        vol_query = vol_query.filter(Evaluation.category == category)
        low_conf_query = low_conf_query.filter(Evaluation.category == category)
        last_query = last_query.filter(Evaluation.category == category)
    if days is not None:
        cutoff = utcnow_naive() - timedelta(days=days)
        conf_query = conf_query.filter(Evaluation.created_at >= cutoff)
        vol_query = vol_query.filter(Evaluation.created_at >= cutoff)
        low_conf_query = low_conf_query.filter(Evaluation.created_at >= cutoff)
        last_query = last_query.filter(Evaluation.created_at >= cutoff)
    avg_conf = conf_query.scalar() or 0.0
    # Count only evaluations that have a corresponding prediction record,
    # matching the inner join used in _breakdown() to avoid inflated counts
    volume = vol_query.scalar() or 0
    low_confidence = low_conf_query.scalar() or 0
    last_submission_at = last_query.scalar()
    # Clamp at 0: if the DB clock ever runs slightly behind the app clock the
    # raw difference could be negative for a just-now submission.
    days_since_last_submission = (
        max(0, (utcnow_naive() - last_submission_at).days) if last_submission_at else None
    )
    return {
        "breakdown": breakdown,
        "average_confidence": round(float(avg_conf), 4),
        "evaluation_volume": volume,
        "low_confidence_count": int(low_confidence),
        "low_confidence_pct": (
            round((low_confidence / volume) * 100, 2) if volume else 0.0
        ),
        "last_submission_at": last_submission_at,
        "days_since_last_submission": days_since_last_submission,
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
        conf_query = conf_query.filter(Evaluation.created_at >= utcnow_naive() - timedelta(days=days))
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
        query = query.filter(Evaluation.created_at >= utcnow_naive() - timedelta(days=days))
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


def _academic_term_lookup() -> tuple[list[str], dict[int, str]]:
    """Return ``(term order, month -> term)`` from the configured calendar.

    The ``evaluations`` table records only the submission timestamp, so an
    academic term is inferred from the month a submission was created in,
    using ``settings.ACADEMIC_TERM_MONTHS`` (see app.core.config). Every
    period is a single calendar month, so a month maps to exactly one term;
    if a month were ever listed by more than one period the first period
    wins. Term names double as chart labels and bucket keys, so the calendar
    must give each period a unique name.
    """
    order: list[str] = []
    month_to_term: dict[int, str] = {}
    for entry in settings.ACADEMIC_TERM_MONTHS or []:
        if not isinstance(entry, dict):
            continue
        term = entry.get("term")
        if not term:
            continue
        term = str(term)
        if term not in order:
            order.append(term)
        for month in entry.get("months") or []:
            try:
                month_number = int(month)
            except (TypeError, ValueError):
                continue
            if 1 <= month_number <= 12 and month_number not in month_to_term:
                month_to_term[month_number] = term
    return order, month_to_term


def term_analytics(
    db: Session,
    days: Optional[int] = None,
    category: Optional[EvaluationCategory] = None,
) -> dict:
    """Sentiment breakdown per academic term (each semester's grading periods).

    Terms are derived from the month each submission was created in via the
    configurable academic calendar — eight single-month periods in the real
    school calendar: Term 1 Prelim..Finals (Jul-Oct) then Term 2
    Prelim..Finals (Feb-May). Months outside that calendar (Nov, Dec, Jan and
    Jun - breaks/enrollment) map to no period and are skipped below, so they
    neither error nor land in the wrong bucket.

    The rows are aggregated into volume + sentiment counts so the dashboard
    can show whether sentiment shifts as the term progresses. Every configured
    term is returned, zero-filled, in calendar order so the chart keeps a
    stable x-axis (the eight defined periods, not all twelve months) even for
    sparse data.
    """
    term_order, month_to_term = _academic_term_lookup()

    query = db.query(Evaluation.created_at, Prediction.official_prediction).join(
        Prediction, Prediction.evaluation_id == Evaluation.id
    )
    if category is not None:
        query = query.filter(Evaluation.category == category)
    if days is not None:
        query = query.filter(Evaluation.created_at >= utcnow_naive() - timedelta(days=days))
    rows = query.all()

    buckets: dict[str, Counter] = {term: Counter() for term in term_order}
    for created_at, label in rows:
        term = month_to_term.get(created_at.month)
        if term is None:
            # Months outside the configured calendar (e.g. a summer break)
            # are excluded rather than guessed into a grading period.
            continue
        buckets[term][label] += 1

    points = []
    for term in term_order:
        counter = buckets.get(term, Counter())
        points.append({
            "term": term,
            "positive": counter.get(SentimentLabel.POSITIVE, 0),
            "neutral": counter.get(SentimentLabel.NEUTRAL, 0),
            "negative": counter.get(SentimentLabel.NEGATIVE, 0),
            "total": sum(counter.values()),
        })

    return {"points": points}


def course_analytics(
    db: Session,
    days: Optional[int] = None,
    category: Optional[EvaluationCategory] = None,
) -> dict:
    """Net sentiment score per course (backs the "Sentiment by Courses" chart).

    The course/program is free text captured by the anonymous evaluation form
    (and by bulk import), stored on the evaluation row itself rather than
    normalised into a lookup table, so it is grouped by its stored value.
    Submissions with no course (NULL or blank) cannot be attributed to any
    program and are skipped instead of being folded into a misleading
    "Unknown" bar.

    Every course gets one score on a -100..+100 scale:

        sentiment_score = (positive - negative) / total * 100

    An all-positive course scores +100, an all-negative one -100, and a course
    with as many positive as negative submissions scores 0. Neutral submissions
    stay in the denominator, so they damp the score toward 0 rather than being
    ignored — ten neutral and one positive submission must not read the same as
    a single positive one.

    Rows are sorted by descending score so the chart reads best-to-worst from
    top to bottom, with submission volume and then the course name as
    tie-breakers so repeated calls return a stable order.
    """
    query = (
        db.query(
            Evaluation.course,
            Prediction.official_prediction,
            func.count(Prediction.id),
        )
        .join(Prediction, Prediction.evaluation_id == Evaluation.id)
        .filter(Evaluation.course.isnot(None))
        .group_by(Evaluation.course, Prediction.official_prediction)
    )
    if category is not None:
        query = query.filter(Evaluation.category == category)
    if days is not None:
        query = query.filter(Evaluation.created_at >= utcnow_naive() - timedelta(days=days))

    buckets: dict[str, Counter] = {}
    for course, label, count in query.all():
        course = (course or "").strip()
        if not course:
            continue
        buckets.setdefault(course, Counter())[label] += count

    points = []
    for course, counter in buckets.items():
        positive = counter.get(SentimentLabel.POSITIVE, 0)
        neutral = counter.get(SentimentLabel.NEUTRAL, 0)
        negative = counter.get(SentimentLabel.NEGATIVE, 0)
        total = positive + neutral + negative
        points.append({
            "course": course,
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "total": total,
            "sentiment_score": round(((positive - negative) / total) * 100, 2) if total else 0.0,
        })

    # Descending score, then the better-evidenced course first on a tie, then
    # case-insensitive name so the bar order never jitters between requests.
    points.sort(key=lambda p: (-p["sentiment_score"], -p["total"], p["course"].lower()))
    return {"points": points}


# ---------------------------------------------------------------------------
# LIKERT ANALYTICS — the numeric half of the feedback
#
# Sentiment is the text signal; Likert is what students actually ticked. Both
# are stored per submission, so these aggregations need no new data and work on
# every historical row.
# ---------------------------------------------------------------------------

# Band captions mirroring the live form's 1-5 scale (js/student.js), so the API
# payload is self-describing for any consumer.
LIKERT_BAND_LABELS: dict[int, str] = {
    1: "Strongly disagree",
    2: "Disagree",
    3: "Neutral",
    4: "Agree",
    5: "Strongly agree",
}

# Short human labels for the aspect keys the live form writes into
# Evaluation.ratings. Unknown keys fall back to a title-cased version of the
# key, so a newly added aspect still renders without a change here.
ASPECT_DISPLAY_NAMES: dict[str, str] = {
    "teaching_quality": "Teaching quality",
    "mastery": "Subject mastery",
    "clarity": "Clarity of explanation",
    "fairness": "Fairness of grading",
    "punctuality": "Punctuality",
    "approachability": "Approachability",
    "feedback": "Constructive feedback",
    "classroom_mgmt": "Classroom management",
    "teaching_style": "Teaching style",
}


def _aspect_label(key: str) -> str:
    if key in ASPECT_DISPLAY_NAMES:
        return ASPECT_DISPLAY_NAMES[key]
    return key.replace("_", " ").strip().capitalize()


def _in_scale(value: float) -> bool:
    from app.services.likert import MAX_SCALE_VALUE, MIN_SCALE_VALUE

    return MIN_SCALE_VALUE <= value <= MAX_SCALE_VALUE


def rating_distribution(
    db: Session,
    category: Optional[EvaluationCategory] = None,
    days: Optional[int] = None,
) -> dict:
    """Histogram of submissions across the five 1-5 Likert bands.

    Every band is always returned, zero-filled, so the x-axis keeps a stable
    1-5 scale instead of collapsing when a band has no submissions. Each band
    also carries the Positive/Neutral/Negative split of those same
    submissions, so the chart can stack and the UI can answer "do the 5s and
    the negative comments come from the same people?".

    ``likert_average`` is a submission's mean of that student's ticks (see
    app.services.likert), rounded to the nearest whole band: 4.4 -> 4, 4.6 ->
    5. Rows with no Likert answer (a comment-only submission) are skipped
    rather than counted as a rating.
    """
    query = (
        db.query(Evaluation.likert_average, Prediction.official_prediction)
        .join(Prediction, Prediction.evaluation_id == Evaluation.id)
    )
    if category is not None:
        query = query.filter(Evaluation.category == category)
    if days is not None:
        query = query.filter(
            Evaluation.created_at >= utcnow_naive() - timedelta(days=days)
        )

    buckets: dict[int, Counter] = {band: Counter() for band in LIKERT_BAND_LABELS}
    values: list[float] = []
    for average, label in query.all():
        if average is None:
            continue
        try:
            value = float(average)
        except (TypeError, ValueError):
            continue
        if not _in_scale(value):
            continue
        values.append(value)
        band = min(max(int(round(value)), 1), 5)
        buckets[band][label] += 1

    points = []
    for band in sorted(LIKERT_BAND_LABELS):
        counter = buckets[band]
        points.append({
            "band": band,
            "label": LIKERT_BAND_LABELS[band],
            "positive": counter.get(SentimentLabel.POSITIVE, 0),
            "neutral": counter.get(SentimentLabel.NEUTRAL, 0),
            "negative": counter.get(SentimentLabel.NEGATIVE, 0),
            "total": sum(counter.values()),
        })

    return {
        "points": points,
        "total": len(values),
        # Mean of the raw values, not of the rounded bands, so a class
        # averaging 4.4 reports 4.4 instead of being flattened to 4.
        "average": round(sum(values) / len(values), 2) if values else None,
    }


def aspect_averages(
    db: Session,
    category: Optional[EvaluationCategory] = None,
    days: Optional[int] = None,
) -> dict:
    """Mean Likert score per rating aspect, strongest first.

    Evaluation.ratings is a JSON object of aspect_key -> 1-5, written by both
    the live form and the bulk importer. Averaging happens in Python rather
    than with JSON_EXTRACT so one code path covers every aspect (including any
    added later), a single malformed value cannot raise a SQL error, and each
    aspect can report how many students answered it — a 4.6 average from three
    students must not read like a 4.6 from three hundred.

    Only aspects that were actually answered appear, sorted by descending
    average: that is the order a horizontal bar chart plots (best at the top)
    and it puts the weakest aspect where the eye lands first.
    """
    query = db.query(Evaluation.ratings).filter(Evaluation.ratings.isnot(None))
    if category is not None:
        query = query.filter(Evaluation.category == category)
    if days is not None:
        query = query.filter(
            Evaluation.created_at >= utcnow_naive() - timedelta(days=days)
        )

    values: dict[str, list[float]] = {}
    for (ratings,) in query.all():
        if not isinstance(ratings, dict):
            continue
        for key, raw in ratings.items():
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not _in_scale(value):
                continue
            values.setdefault(str(key), []).append(value)

    points = [
        {
            "aspect": key,
            "label": _aspect_label(key),
            "average": round(sum(scores) / len(scores), 2),
            "responses": len(scores),
        }
        for key, scores in values.items()
    ]
    points.sort(key=lambda p: (-p["average"], p["label"].lower()))

    return {
        "points": points,
        "total": sum(p["responses"] for p in points),
    }


def _academic_cycle_position(month: int, anchor_month: int) -> int:
    """Where ``month`` sits in the academic cycle, measured from ``anchor_month``.

    The configured calendar wraps across the new year (Term 1 runs Jul-Oct and
    Term 2 runs Feb-May of the following calendar year), so plain month numbers
    cannot be compared directly. Measuring the distance forward from the first
    configured month puts every period on one monotonically increasing timeline
    (e.g. for a July anchor: Jul=0 ... Oct=3, Feb=7 ... May=10, with the break
    months landing at 4-6 and 11).
    """
    return (month - anchor_month) % 12


def _cycle_anchor_month(order: list[str], month_to_term: dict[int, str]) -> Optional[int]:
    """First month of the first configured term — the start of the academic year."""
    if not order:
        return None
    first_term_months = [m for m, t in month_to_term.items() if t == order[0]]
    return min(first_term_months) if first_term_months else None


def _latest_completed_term(
    order: list[str],
    month_to_term: dict[int, str],
    month: int,
) -> Optional[str]:
    """The grading period whose month most recently ended before ``month``.

    Only needed for break months (Nov, Dec, Jan, Jun), which belong to no
    grading period themselves: the Overview widget then compares the two most
    recently completed periods instead of an active one. Positions come from
    the configured calendar rather than a hard-coded month list, so changing
    ACADEMIC_TERM_MONTHS keeps this in sync.
    """
    anchor = _cycle_anchor_month(order, month_to_term)
    if anchor is None:
        return None
    target = _academic_cycle_position(month, anchor)
    best_term: Optional[str] = None
    best_position = -1
    for month_number, term in month_to_term.items():
        position = _academic_cycle_position(month_number, anchor)
        if position < target and position > best_position:
            best_position = position
            best_term = term
    return best_term


def _term_summary(term: Optional[str], point: Optional[dict]) -> Optional[dict]:
    """Turn a zero-filled term_analytics() point into the widget's side payload."""
    if not term:
        return None
    point = point or {}
    positive = point.get("positive", 0)
    neutral = point.get("neutral", 0)
    negative = point.get("negative", 0)
    total = point.get("total", 0) or (positive + neutral + negative)
    pct = lambda n: round((n / total) * 100, 2) if total else 0.0  # noqa: E731
    return {
        "term": term,
        "positive": positive,
        "neutral": neutral,
        "negative": negative,
        "total": total,
        "positive_pct": pct(positive),
        "neutral_pct": pct(neutral),
        "negative_pct": pct(negative),
    }


def term_comparison(
    db: Session,
    days: Optional[int] = None,
    category: Optional[EvaluationCategory] = None,
) -> dict:
    """Current grading period vs the one immediately before it (Overview widget).

    "Current" is nothing more than today's month run through the same
    ``_academic_term_lookup()`` the Analytics term chart uses — there is no
    separate notion of "now" for terms, so the two can never disagree. The
    comparison is against the period immediately preceding it in the
    configured order (e.g. Term 1 Prefinal vs Term 1 Midterm), not a fixed
    Term 1 vs Term 2 pairing.

    Break months (Nov, Dec, Jan, Jun) have no active period, so the widget
    falls back to the two most recently completed periods and says so in
    ``note``. When there is no preceding period at all — the current period is
    the first in the calendar, or the two periods carry no submissions — that
    side is returned as ``None`` and ``note`` explains it, so the frontend
    renders a single period instead of a broken comparison.

    Bucketing is delegated to ``term_analytics()`` so this widget and the
    Analytics term chart always report identical numbers for the same period.
    """
    data = term_analytics(db, days=days, category=category)
    points = {p["term"]: p for p in data["points"]}
    order, month_to_term = _academic_term_lookup()

    today = utcnow_naive()
    is_break_month = today.month not in month_to_term
    current_name = month_to_term.get(today.month)
    if current_name is None:
        current_name = _latest_completed_term(order, month_to_term, today.month)

    previous_name: Optional[str] = None
    if current_name in order:
        index = order.index(current_name)
        if index > 0:
            previous_name = order[index - 1]

    current = _term_summary(current_name, points.get(current_name) if current_name else None)
    previous = _term_summary(previous_name, points.get(previous_name) if previous_name else None)

    if current is None:
        note = (
            "No grading period is configured for the current month, so there is "
            "nothing to compare yet."
        )
    elif previous is None:
        note = (
            f"{current_name} is the first grading period in the configured calendar, "
            "so there is no earlier period to compare it against."
        )
    elif is_break_month:
        note = (
            f"Today falls in a break / enrollment month with no active grading period, "
            f"so this compares the two most recently completed periods "
            f"({previous_name} then {current_name})."
        )
    else:
        note = (
            f"Comparing the current grading period ({current_name}) with the one "
            f"immediately before it ({previous_name})."
        )

    return {
        "current_term": current_name,
        "previous_term": previous_name,
        "is_break_month": is_break_month,
        "reference_month": today.strftime("%Y-%m"),
        "current": current,
        "previous": previous,
        "note": note,
    }


_WORD_PATTERN = re.compile(r"[a-zA-Z']+")


def word_frequency(
    db: Session,
    sentiment: SentimentLabel,
    top_n: int = 30,
    category: Optional[EvaluationCategory] = None,
) -> dict:
    """Most frequent comment words for one sentiment, optionally one category.

    ``category`` narrows to a single evaluation category. It is REQUIRED for
    the scoping to be meaningful: this endpoint had no category parameter at
    all, so it was the one analytics route a faculty token could read without
    restriction -- the word frequency of Staff / Facilities / Payments
    comments was reachable by anyone who could sign in as faculty. The route
    now accepts the filter and pins it to Professors for faculty accounts,
    the same as every other panel on their dashboard.
    """
    query = (
        db.query(Evaluation.comment)
        .join(Prediction, Prediction.evaluation_id == Evaluation.id)
        .filter(Prediction.official_prediction == sentiment)
    )
    if category is not None:
        query = query.filter(Evaluation.category == category)
    rows = query.all()

    counter: Counter = Counter()
    for (comment,) in rows:
        words = [w.lower() for w in _WORD_PATTERN.findall(comment or "")]
        words = [w for w in words if w not in STOPWORDS and len(w) > 2]
        counter.update(words)

    top_words = [{"word": w, "count": c} for w, c in counter.most_common(top_n)]
    return {"sentiment": sentiment.value, "words": top_words}


def top_comments(
    db: Session,
    kind: str,
    limit: int = 10,
    category: Optional[EvaluationCategory] = None,
) -> dict:
    """kind='complaints' -> highest-confidence, purely Negative comments.
    kind='appreciations' -> highest-confidence, purely Positive comments.

    ``category`` narrows the panel to a single evaluation category (the Faculty
    dashboard is scoped to Professors). ``None`` keeps every category, which is
    what the Admin panel wants.

    "Purely" means the comment's ML sentiment is NOT contradicted by the
    same submission's Likert rating (Evaluation.is_mismatch is False).
    A comment whose text reads negative but whose Likert score reads
    positive (or vice versa) is a mixed signal, not a clean complaint or
    appreciation, so it's excluded here even if its text-sentiment
    confidence is high. See app.services.mismatch for how is_mismatch is
    derived.
    """
    target = SentimentLabel.NEGATIVE if kind == "complaints" else SentimentLabel.POSITIVE

    query = (
        db.query(Evaluation, Prediction)
        .join(Prediction, Prediction.evaluation_id == Evaluation.id)
        .filter(Prediction.official_prediction == target)
        .filter(Evaluation.is_mismatch.is_(False))
    )
    if category is not None:
        query = query.filter(Evaluation.category == category)
    rows = query.order_by(Prediction.confidence_score.desc()).limit(limit).all()

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