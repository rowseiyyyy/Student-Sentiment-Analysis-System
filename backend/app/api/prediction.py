from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.prediction import PredictionRequest, PredictionResponse, SingleModelResult
from app.services.prediction import run_prediction_pipeline

router = APIRouter(prefix="/predict", tags=["Prediction"])


@router.post("", response_model=PredictionResponse)
@limiter.limit("20/minute")
def predict_sentiment(
    request: Request,
    payload: PredictionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ad-hoc sentiment prediction (does not persist an Evaluation row).
    Useful for the Admin Panel to test model behavior on arbitrary text."""
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="text must not be empty.")

    try:
        result = run_prediction_pipeline(db, payload.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    return PredictionResponse(
        text=payload.text,
        xgb=SingleModelResult(prediction=result["xgb_prediction"], confidence=result["xgb_confidence"]),
        deberta=SingleModelResult(prediction=result["deberta_prediction"], confidence=result["deberta_confidence"]),
        roberta=SingleModelResult(prediction=result["roberta_prediction"], confidence=result["roberta_confidence"]),
        ensemble=SingleModelResult(
            prediction=result["ensemble_prediction"], confidence=result["ensemble_confidence"]
        ),
        official_prediction=result["official_prediction"],
        algorithm_used=result["algorithm_used"],
        confidence_score=result["confidence_score"],
        processing_time_ms=result["processing_time_ms"],
    )
