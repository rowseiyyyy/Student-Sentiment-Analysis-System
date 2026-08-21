from datetime import datetime

from pydantic import BaseModel

from app.models.training_history import TrainingAlgorithm, TrainingStatus


class TrainRequest(BaseModel):
    dataset_filename: str | None = None
    n_estimators: int = 300
    max_depth: int | None = None
    min_samples_split: int = 2


class TrainingHistoryOut(BaseModel):
    id: str
    algorithm: TrainingAlgorithm
    status: TrainingStatus
    dataset_filename: str | None
    dataset_size: int | None
    accuracy: float | None
    precision: float | None
    recall: float | None
    f1_score: float | None
    macro_f1: float | None
    weighted_f1: float | None
    training_time_seconds: float | None
    inference_time_ms: float | None
    memory_usage_mb: float | None
    is_production_model: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ModelComparisonRow(BaseModel):
    algorithm: str
    accuracy: float | None
    precision: float | None
    recall: float | None
    f1_score: float | None
    training_time_seconds: float | None
    inference_time_ms: float | None
    is_production_model: bool


class ModelComparisonResponse(BaseModel):
    best_model: str | None
    rows: list[ModelComparisonRow]


class ConfusionMatrixResponse(BaseModel):
    algorithm: str
    labels: list[str]
    matrix: list[list[int]]


class ClassificationReportResponse(BaseModel):
    algorithm: str
    report: dict
