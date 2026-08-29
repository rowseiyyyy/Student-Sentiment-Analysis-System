from datetime import datetime

from pydantic import BaseModel

from app.models.prediction import AlgorithmName, SentimentLabel


class PredictionRequest(BaseModel):
    text: str


class SingleModelResult(BaseModel):
    prediction: SentimentLabel | None
    confidence: float | None


class PredictionOut(BaseModel):
    id: str
    evaluation_id: str
    xgb_prediction: SentimentLabel | None = None
    xgb_confidence: float | None = None
    deberta_prediction: SentimentLabel | None = None
    deberta_confidence: float | None = None
    roberta_prediction: SentimentLabel | None = None
    roberta_confidence: float | None = None
    # Backward-compat three-model soft-vote report (see
    # run_prediction_pipeline's ensemble_prediction/ensemble_confidence).
    # Distinct from `official_prediction`, which follows whatever approach
    # (single model or ensemble) is currently selected as production.
    ensemble_prediction: SentimentLabel | None = None
    ensemble_confidence: float | None = None
    official_prediction: SentimentLabel
    algorithm_used: AlgorithmName
    confidence_score: float
    processing_time_ms: float
    created_at: datetime

    class Config:
        from_attributes = True


class PredictionResponse(BaseModel):
    text: str
    xgb: SingleModelResult | None = None
    deberta: SingleModelResult | None = None
    roberta: SingleModelResult | None = None
    ensemble: SingleModelResult | None = None
    official_prediction: SentimentLabel
    algorithm_used: str
    confidence_score: float
    processing_time_ms: float