from datetime import datetime

from pydantic import BaseModel, Field

VALID_SENTIMENTS = {"Positive", "Neutral", "Negative"}


class VoiceNoteCreate(BaseModel):
    """Submission payload for a Voice in a Box entry.

    Deliberately ONLY contains the free-text message: there is no
    student_id, course, year_level, name, email, or any other identity
    field — and the server never accepts one for this endpoint, so a
    crafted request body cannot attach an identity to a submission.
    """

    message: str = Field(min_length=3, max_length=5000)


class VoiceNoteOut(BaseModel):
    id: str
    message: str
    sentiment: str | None = None
    confidence_score: float | None = None
    algorithm_used: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VoiceNoteListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[VoiceNoteOut]


class VoiceNoteStats(BaseModel):
    """Feed-local counts for the Voice in a Box stream only.

    These numbers are never merged into the evaluation analytics/KPI
    endpoints — they exist purely so the Voice in a Box feed can show
    "n entries" for its own scope.
    """

    total: int
    positive: int
    neutral: int
    negative: int
