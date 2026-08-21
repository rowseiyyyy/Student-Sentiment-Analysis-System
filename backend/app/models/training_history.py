import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TrainingAlgorithm(str, enum.Enum):
    # Historical / legacy rows remain readable.
    SVM = "SVM"
    RANDOM_FOREST = "Random Forest"
    NAIVE_BAYES = "Naive Bayes"
    BERT = "BERT"

    # Approved active research models.
    XGBOOST = "XGBoost"
    DEBERTA = "DeBERTa"
    ROBERTA = "RoBERTa"

    # Approved ensembles (weighted soft voting). ``ENSEMBLE`` is retained
    # as a legacy alias for historical rows; new runs use the explicit
    # member-based ensemble names below.
    ENSEMBLE = "Ensemble"
    ENSEMBLE_XGB_DEBERTA = "XGBoost + DeBERTa"
    ENSEMBLE_DEBERTA_ROBERTA = "DeBERTa + RoBERTa"
    ENSEMBLE_ROBERTA_XGB = "RoBERTa + XGBoost"
    ENSEMBLE_XGB_DEBERTA_ROBERTA = "XGBoost + DeBERTa + RoBERTa"


class TrainingStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TrainingHistory(Base):
    __tablename__ = "training_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    algorithm: Mapped[TrainingAlgorithm] = mapped_column(Enum(TrainingAlgorithm), nullable=False)
    status: Mapped[TrainingStatus] = mapped_column(
        Enum(TrainingStatus), default=TrainingStatus.RUNNING, nullable=False
    )

    dataset_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    macro_f1: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_f1: Mapped[float | None] = mapped_column(Float, nullable=True)

    training_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    inference_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_usage_mb: Mapped[float | None] = mapped_column(Float, nullable=True)

    confusion_matrix: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    classification_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hyperparameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_production_model: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
