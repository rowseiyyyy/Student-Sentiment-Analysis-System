import csv
import io

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_staff
from app.core.database import get_db, retry_on_disconnect
from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction, SentimentLabel
from app.models.user import User, UserRole
from app.schemas.analytics import (
    AspectAveragesResponse,
    CategoryAnalyticsResponse,
    CourseAnalyticsResponse,
    OverallAnalyticsResponse,
    RatingDistributionResponse,
    TermAnalyticsResponse,
    TermComparisonResponse,
    TopCommentsResponse,
    TrendResponse,
    WordFrequencyResponse,
)
from app.schemas.evaluation import NormalizedCategory
from app.services import analytics as analytics_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _days_param(days: Optional[int]) -> Optional[int]:
    """Shared validation for the optional ``days`` date-range filter."""
    if days is None:
        return None
    if not 1 <= days <= 3650:
        raise ValueError("days must be between 1 and 3650")
    return days


# A faculty account reviews professor feedback only: its dashboard panels
# (Monthly Trend, Sentiment by Courses, Top Comments) are scoped to the
# Professors category and must never mix in Staff / Facilities / Payments rows.
# Enforced server-side as well as in the UI, so a faculty token cannot widen
# its own view by hand-crafting ?category=Staff. Administrators are untouched:
# they keep the all-categories view (or whatever category they ask for).
FACULTY_SCOPE_CATEGORY = EvaluationCategory.PROFESSOR


def _scoped_category(
    category: Optional[NormalizedCategory],
    current_user: User,
) -> Optional[NormalizedCategory]:
    """Pin the category for faculty accounts; pass it through for everyone else.

    ``None`` (no filter) is a valid request for an administrator and means
    "all categories", so it is only ever overridden for the faculty role.
    """
    if current_user.role == UserRole.FACULTY:
        return FACULTY_SCOPE_CATEGORY
    return category


@router.get("/overall", response_model=OverallAnalyticsResponse)
@retry_on_disconnect()
def get_overall_analytics(
    days: Optional[int] = Query(None, ge=1, le=3650, description="Only include submissions from the last N days."),
    category: Optional[NormalizedCategory] = Query(None, description="Restrict to one department/category."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.overall_analytics(
        db,
        category=_scoped_category(category, current_user),
        days=_days_param(days),
    )


@router.get("/category", response_model=CategoryAnalyticsResponse)
@retry_on_disconnect()
def get_category_analytics(
    category: NormalizedCategory,
    days: Optional[int] = Query(None, ge=1, le=3650, description="Only include submissions from the last N days."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.category_analytics(db, category, days=_days_param(days))


@router.get("/monthly", response_model=TrendResponse)
@retry_on_disconnect()
def get_monthly_trend(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.trend_analytics(
        db,
        granularity="monthly",
        days=_days_param(days),
        category=_scoped_category(category, current_user),
    )


@router.get("/daily", response_model=TrendResponse)
@retry_on_disconnect()
def get_daily_trend(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.trend_analytics(db, granularity="daily", days=_days_param(days), category=category)


@router.get("/terms", response_model=TermAnalyticsResponse)
@retry_on_disconnect()
def get_term_analytics(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.term_analytics(db, days=_days_param(days), category=category)


@router.get("/term-comparison", response_model=TermComparisonResponse)
@retry_on_disconnect()
def get_term_comparison(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Current grading period vs the one before it — backs the Overview
    term-over-term widget. "Current" is resolved from today's month with the
    same configured calendar the /analytics/terms chart uses."""
    return analytics_service.term_comparison(db, days=_days_param(days), category=category)


@router.get("/courses", response_model=CourseAnalyticsResponse)
@retry_on_disconnect()
def get_course_analytics(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Net sentiment score per course — backs the "Sentiment by Courses"
    horizontal bar chart (course names on the Y axis, score on the X axis).
    Rows come back sorted by descending score, which is the order the chart
    plots them in: the best-scoring course sits at the top."""
    return analytics_service.course_analytics(
        db,
        days=_days_param(days),
        category=_scoped_category(category, current_user),
    )


@router.get("/word-frequency", response_model=WordFrequencyResponse)
@retry_on_disconnect()
def get_word_frequency(
    sentiment: SentimentLabel,
    top_n: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.word_frequency(db, sentiment, top_n=top_n)


@router.get("/ratings/distribution", response_model=RatingDistributionResponse)
@retry_on_disconnect()
def get_rating_distribution(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(
        None, description="Restrict to one category. Pinned to Professors for faculty accounts."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """1-5 Likert histogram, each band split by that submission's sentiment.

    Backs the faculty "Rating Distribution" chart: are students ticking 4-5
    while writing negative comments, or genuinely unhappy?
    """
    return analytics_service.rating_distribution(
        db,
        days=_days_param(days),
        category=_scoped_category(category, current_user),
    )


@router.get("/ratings/aspects", response_model=AspectAveragesResponse)
@retry_on_disconnect()
def get_aspect_averages(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(
        None, description="Restrict to one category. Pinned to Professors for faculty accounts."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Mean Likert score per rating aspect, strongest first.

    Backs the faculty "Average by Aspect" chart — the "strong on clarity,
    weak on punctuality" view, read straight from Evaluation.ratings.
    """
    return analytics_service.aspect_averages(
        db,
        days=_days_param(days),
        category=_scoped_category(category, current_user),
    )


@router.get("/top-complaints", response_model=TopCommentsResponse)
@retry_on_disconnect()
def get_top_complaints(
    limit: int = Query(10, ge=1, le=100),
    category: Optional[NormalizedCategory] = Query(
        None, description="Restrict to one category. Pinned to Professors for faculty accounts."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.top_comments(
        db,
        kind="complaints",
        limit=limit,
        category=_scoped_category(category, current_user),
    )


@router.get("/top-appreciations", response_model=TopCommentsResponse)
@retry_on_disconnect()
def get_top_appreciations(
    limit: int = Query(10, ge=1, le=100),
    category: Optional[NormalizedCategory] = Query(
        None, description="Restrict to one category. Pinned to Professors for faculty accounts."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.top_comments(
        db,
        kind="appreciations",
        limit=limit,
        category=_scoped_category(category, current_user),
    )


@router.get("/export/csv")
@retry_on_disconnect()
def export_evaluations_csv(
    category: Optional[NormalizedCategory] = Query(
        None, description="Restrict to one category. Pinned to Professors for faculty accounts."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Streams evaluations + predictions as a downloadable CSV report.

    Faculty accounts are pinned to the Professors category (same scope as the
    rest of their dashboard — see _scoped_category), so the report cannot be
    used as a back door to the Staff / Facilities / Payments comments.
    Administrators get every category unless they narrow it themselves.
    """
    query = db.query(Evaluation, Prediction).join(
        Prediction, Prediction.evaluation_id == Evaluation.id
    )
    scoped = _scoped_category(category, current_user)
    if scoped is not None:
        query = query.filter(Evaluation.category == scoped)
    rows = query.order_by(Evaluation.created_at.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "evaluation_id", "category", "comment", "sentiment", "official_prediction", "algorithm_used",
        "confidence_score", "svm_prediction", "svm_confidence",
        "naive_bayes_prediction", "naive_bayes_confidence",
        "logistic_regression_prediction", "logistic_regression_confidence",
        "created_at",
    ])
    for ev, pred in rows:
        writer.writerow([
            ev.id, ev.category.value, ev.comment, ev.sentiment or "", pred.official_prediction.value,
            pred.algorithm_used.value, pred.confidence_score,
            pred.svm_prediction.value if pred.svm_prediction else "",
            pred.svm_confidence if pred.svm_confidence else "",
            pred.naive_bayes_prediction.value if pred.naive_bayes_prediction else "",
            pred.naive_bayes_confidence if pred.naive_bayes_confidence else "",
            pred.logistic_regression_prediction.value if pred.logistic_regression_prediction else "",
            pred.logistic_regression_confidence if pred.logistic_regression_confidence else "",
            ev.created_at.isoformat(),
        ])
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluations_report.csv"},
    )
