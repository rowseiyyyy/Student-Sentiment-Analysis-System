import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction, SentimentLabel
from app.models.user import User
from app.schemas.analytics import (
    CategoryAnalyticsResponse,
    OverallAnalyticsResponse,
    TopCommentsResponse,
    TrendResponse,
    WordFrequencyResponse,
)
from app.services import analytics as analytics_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/overall", response_model=OverallAnalyticsResponse)
def get_overall_analytics(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return analytics_service.overall_analytics(db)


@router.get("/category", response_model=CategoryAnalyticsResponse)
def get_category_analytics(
    category: EvaluationCategory,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.category_analytics(db, category)


@router.get("/monthly", response_model=TrendResponse)
def get_monthly_trend(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return analytics_service.trend_analytics(db, granularity="monthly")


@router.get("/daily", response_model=TrendResponse)
def get_daily_trend(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return analytics_service.trend_analytics(db, granularity="daily")


@router.get("/word-frequency", response_model=WordFrequencyResponse)
def get_word_frequency(
    sentiment: SentimentLabel,
    top_n: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.word_frequency(db, sentiment, top_n=top_n)


@router.get("/top-complaints", response_model=TopCommentsResponse)
def get_top_complaints(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.top_comments(db, kind="complaints", limit=limit)


@router.get("/top-appreciations", response_model=TopCommentsResponse)
def get_top_appreciations(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.top_comments(db, kind="appreciations", limit=limit)


@router.get("/export/csv")
def export_evaluations_csv(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
        "confidence_score", "svm_prediction", "svm_confidence",
        "random_forest_prediction", "random_forest_confidence",
        "naive_bayes_prediction", "naive_bayes_confidence",
        "bert_prediction", "bert_confidence",
        "created_at",
    ])
    for ev, pred in rows:
        writer.writerow([
            ev.id, ev.category.value, ev.comment, ev.sentiment or "", pred.official_prediction.value,
            pred.algorithm_used.value, pred.confidence_score,
            pred.svm_prediction.value if pred.svm_prediction else "",
            pred.svm_confidence if pred.svm_confidence else "",
            pred.random_forest_prediction.value if pred.random_forest_prediction else "",
            pred.random_forest_confidence if pred.random_forest_confidence else "",
            pred.naive_bayes_prediction.value if pred.naive_bayes_prediction else "",
            pred.naive_bayes_confidence if pred.naive_bayes_confidence else "",
            pred.bert_prediction.value if pred.bert_prediction else "",
            pred.bert_confidence if pred.bert_confidence else "",
            ev.created_at.isoformat(),
        ])
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluations_report.csv"},
    )
