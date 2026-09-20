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
    # Approved research models (the 4-model set).
    SVM = "SVM"
    NAIVE_BAYES = "Naive Bayes"
    LOGISTIC_REGRESSION = "Logistic Regression"
    MINILM = "Multilingual MiniLM"


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluations.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # ----- Per-model predictions (research set; MiniLM is the only live
    # model and is not stored per-row here — only the official result is) -----
    svm_prediction: Mapped[SentimentLabel | None] = mapped_column(Enum(SentimentLabel), nullable=True)
    svm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    naive_bayes_prediction: Mapped[SentimentLabel | None] = mapped_column(Enum(SentimentLabel), nullable=True)
    naive_bayes_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    logistic_regression_prediction: Mapped[SentimentLabel | None] = mapped_column(Enum(SentimentLabel), nullable=True)
    logistic_regression_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Official (production) prediction
    official_prediction: Mapped[SentimentLabel] = mapped_column(Enum(SentimentLabel), nullable=False)
    algorithm_used: Mapped[AlgorithmName] = mapped_column(Enum(AlgorithmName), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)

    processing_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    evaluation = relationship("Evaluation", back_populates="prediction")
