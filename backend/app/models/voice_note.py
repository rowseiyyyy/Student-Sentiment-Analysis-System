"""
"Voice in a Box" — open-ended, fully anonymous feedback submissions.

A deliberately SEPARATE feedback stream from the evaluation-form
responses (``evaluations`` table). A Voice in a Box entry is a single
free-text message about a student's overall school experience — it has
no course, no instructor, no Likert ratings, no evaluatee, and above
all NO student identifier of any kind (no user_id, no student_id
column even exists here).

These rows are intentionally excluded from every existing aggregate
(Total Evaluations, department/category breakdowns, term charts,
Overview cards, Analytics, alerting): those KPIs are all derived from
the ``evaluations``/``predictions`` tables, which this model never
touches. Voice in a Box entries carry their own ML sentiment label
(Positive/Neutral/Negative + confidence) computed by the same live
prediction pipeline used for evaluation responses.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import utcnow_naive


class VoiceNote(Base):
    __tablename__ = "voice_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # The open-ended message itself. This is the ONLY content captured —
    # there is no author, no student number, no course, no section, no IP
    # column, nothing identity-shaped on this table.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Official production sentiment label ("Positive"/"Neutral"/"Negative")
    # produced by the same live pipeline used for evaluation responses.
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # Confidence score (0-1) of the sentiment prediction at submit time.
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Which approved model/ensemble produced the label (e.g. "Multilingual MiniLM").
    algorithm_used: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Inference wall time (ms) recorded for parity with evaluation predictions.
    processing_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)
