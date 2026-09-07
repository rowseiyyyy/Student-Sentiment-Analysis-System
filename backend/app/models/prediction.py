import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.time import utcnow_naive


class SentimentLabel(str, enum.Enum):
    POSITIVE = "Positive"
    NEUTRAL = "Neutral"
    NEGATIVE = "Negative"


class AlgorithmName(str, enum.Enum):
    XGBOOST = "XGBoost"
    XGBOOST_TFDF = "XGBoost (TF-DF)"
    MDEBERTA = "mDeBERTa"
    XLM_ROBERTA = "XLM-RoBERTa"
    LEGACY_XGBOOST = "XGBoost"
    DEBERTA = "DeBERTa"
    ROBERTA = "RoBERTa"
    LEGACY_ENSEMBLE_SOFT_VOTE = "Ensemble (soft vote)"
    ENSEMBLE_XGB_DEBERTA = "XGBoost + DeBERTa"
    ENSEMBLE_DEBERTA_ROBERTA = "DeBERTa + RoBERTa"
    ENSEMBLE_ROBERTA_XGB = "RoBERTa + XGBoost"
    ENSEMBLE_XGB_DEBERTA_ROBERTA = "XGBoost + DeBERTa + RoBERTa"
    ENSEMBLE_TFDF_MDEBERTA = "XGBoost (TF-DF) + mDeBERTa"
    ENSEMBLE_MDEBERTA_XLM = "mDeBERTa + XLM-RoBERTa"
    ENSEMBLE_XLM_TFDF = "XLM-RoBERTa + XGBoost (TF-DF)"
    ENSEMBLE_TFDF_MDEBERTA_XLM = "XGBoost (TF-DF) + mDeBERTa + XLM-RoBERTa"


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluations.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # ----- Per-model predictions -----
    xgb_prediction: Mapped[SentimentLabel | None] = mapped_column(Enum(SentimentLabel), nullable=True)
    xgb_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    deberta_prediction: Mapped[SentimentLabel | None] = mapped_column(Enum(SentimentLabel), nullable=True)
    deberta_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    roberta_prediction: Mapped[SentimentLabel | None] = mapped_column(Enum(SentimentLabel), nullable=True)
    roberta_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Official (production) prediction
    official_prediction: Mapped[SentimentLabel] = mapped_column(Enum(SentimentLabel), nullable=False)
    algorithm_used: Mapped[AlgorithmName] = mapped_column(Enum(AlgorithmName), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)

    processing_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    evaluation = relationship("Evaluation", back_populates="prediction")
