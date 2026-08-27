import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.services.mismatch import MismatchType


class EvaluationCategory(str, enum.Enum):
    FACULTY = "Faculty"
    STAFF = "Staff"
    PAYMENT = "Payment"
    FACILITIES = "Facilities"


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    evaluatee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[EvaluationCategory] = mapped_column(Enum(EvaluationCategory), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    cleaned_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # FIX: the evaluation form was consolidated down to a single
    # open-ended "Share your thoughts" field (was previously two
    # separate fields: strengths / areas_for_improvement). This column
    # replaces both. See app/schemas/evaluation.py (EvaluationCreate /
    # EvaluationOut) and app/api/evaluation.py, which were already
    # updated to read/write `share_your_thoughts` — this model was the
    # missing piece, and its absence was the direct cause of the 500
    # ("Internal Server Error... is not valid JSON") on submit.
    share_your_thoughts: Mapped[str | None] = mapped_column(Text, nullable=True)
    ratings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    likert_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    likert_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_mismatch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    mismatch_type: Mapped[str] = mapped_column(
        String(30), default=MismatchType.NONE.value, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    @property
    def student(self) -> dict[str, Any] | None:
        if not self.submitted_by:
            return None
        return {
            "student_id": self.submitted_by.student_id,
            "course": self.submitted_by.course,
            "year_level": self.submitted_by.year_level,
            "full_name": self.submitted_by.full_name,
        }

    @property
    def student_info(self) -> dict[str, Any] | None:
        return self.student

    submitted_by = relationship("User", back_populates="evaluations")
    prediction = relationship(
        "Prediction", back_populates="evaluation", uselist=False, cascade="all, delete-orphan"
    )
