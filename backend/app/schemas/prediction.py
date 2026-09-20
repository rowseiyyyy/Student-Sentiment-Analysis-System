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
    # Research-set per-model results (never run live — always None; kept so
    # historical rows stay readable). The official result is Multilingual MiniLM.
    svm_prediction: SentimentLabel | None = None
    svm_confidence: float | None = None
    naive_bayes_prediction: SentimentLabel | None = None
    naive_bayes_confidence: float | None = None
    logistic_regression_prediction: SentimentLabel | None = None
    logistic_regression_confidence: float | None = None
    official_prediction: SentimentLabel
    algorithm_used: AlgorithmName
    confidence_score: float
    processing_time_ms: float
    created_at: datetime

    class Config:
        from_attributes = True


class PredictionResponse(BaseModel):
    """Live ad-hoc prediction result. Multilingual MiniLM is the ONLY live
    model, so the response carries its result plus the official (production)
    prediction — no per-model fields (SVM / Naive Bayes / Logistic
    Regression) are included."""

    text: str
    minilm: SingleModelResult | None = None
    official_prediction: SentimentLabel
    algorithm_used: str
    confidence_score: float
    processing_time_ms: float