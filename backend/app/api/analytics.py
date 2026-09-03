import csv
import io

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_staff
from app.core.database import get_db
from app.models.evaluation import Evaluation
from app.models.prediction import Prediction, SentimentLabel
from app.models.user import User
from app.schemas.analytics import (
    CategoryAnalyticsResponse,
    OverallAnalyticsResponse,
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


@router.get("/overall", response_model=OverallAnalyticsResponse)
def get_overall_analytics(
    days: Optional[int] = Query(None, ge=1, le=3650, description="Only include submissions from the last N days."),
    category: Optional[NormalizedCategory] = Query(None, description="Restrict to one department/category."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.overall_analytics(db, category=category, days=_days_param(days))


@router.get("/category", response_model=CategoryAnalyticsResponse)
def get_category_analytics(
    category: NormalizedCategory,
    days: Optional[int] = Query(None, ge=1, le=3650, description="Only include submissions from the last N days."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.category_analytics(db, category, days=_days_param(days))


@router.get("/monthly", response_model=TrendResponse)
def get_monthly_trend(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.trend_analytics(db, granularity="monthly", days=_days_param(days), category=category)


@router.get("/daily", response_model=TrendResponse)
def get_daily_trend(
    days: Optional[int] = Query(None, ge=1, le=3650),
    category: Optional[NormalizedCategory] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.trend_analytics(db, granularity="daily", days=_days_param(days), category=category)


@router.get("/word-frequency", response_model=WordFrequencyResponse)
def get_word_frequency(
    sentiment: SentimentLabel,
    top_n: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.word_frequency(db, sentiment, top_n=top_n)


@router.get("/top-complaints", response_model=TopCommentsResponse)
def get_top_complaints(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.top_comments(db, kind="complaints", limit=limit)


@router.get("/top-appreciations", response_model=TopCommentsResponse)
def get_top_appreciations(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return analytics_service.top_comments(db, kind="appreciations", limit=limit)


@router.get("/export/csv")
def export_evaluations_csv(db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    """Streams all evaluations + predictions as a downloadable CSV report."""
    rows = (
        db.query(Evaluation, Prediction)
        .join(Prediction, Prediction.evaluation_id == Evaluation.id)
        .order_by(Evaluation.created_at.desc())
        .all()
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "evaluation_id", "category", "comment", "sentiment", "official_prediction", "algorithm_used",
        "confidence_score", "xgb_prediction", "xgb_confidence",
        "deberta_prediction", "deberta_confidence",
        "roberta_prediction", "roberta_confidence",
        "created_at",
    ])
    for ev, pred in rows:
        writer.writerow([
            ev.id, ev.category.value, ev.comment, ev.sentiment or "", pred.official_prediction.value,
            pred.algorithm_used.value, pred.confidence_score,
            pred.xgb_prediction.value if pred.xgb_prediction else "",
            pred.xgb_confidence if pred.xgb_confidence else "",
            pred.deberta_prediction.value if pred.deberta_prediction else "",
            pred.deberta_confidence if pred.deberta_confidence else "",
            pred.roberta_prediction.value if pred.roberta_prediction else "",
            pred.roberta_confidence if pred.roberta_confidence else "",
            ev.created_at.isoformat(),
        ])
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluations_report.csv"},
    )
