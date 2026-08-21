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
    svm_prediction: SentimentLabel | None
    svm_confidence: float | None
    random_forest_prediction: SentimentLabel | None
    random_forest_confidence: float | None
    naive_bayes_prediction: SentimentLabel | None
    naive_bayes_confidence: float | None
    bert_prediction: SentimentLabel | None
    bert_confidence: float | None
    official_prediction: SentimentLabel
    algorithm_used: AlgorithmName
    confidence_score: float
    processing_time_ms: float
    created_at: datetime

    class Config:
        from_attributes = True


class PredictionResponse(BaseModel):
    text: str
    svm: SingleModelResult
    random_forest: SingleModelResult
    naive_bayes: SingleModelResult
    bert: SingleModelResult
    xgb: SingleModelResult | None = None
    deberta: SingleModelResult | None = None
    roberta: SingleModelResult | None = None
    ensemble: SingleModelResult | None = None
    official_prediction: SentimentLabel
    algorithm_used: str
    confidence_score: float
    processing_time_ms: float
