from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SentimentBreakdown(BaseModel):
    positive: int
    neutral: int
    negative: int
    total: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float


class OverallAnalyticsResponse(BaseModel):
    breakdown: SentimentBreakdown
    average_confidence: float
    evaluation_volume: int
    # Health-snapshot extras (Overview tab). Defaults keep older callers and
    # fixtures working without every field having to be supplied.
    low_confidence_count: int = 0
    low_confidence_pct: float = 0.0
    last_submission_at: Optional[datetime] = None
    days_since_last_submission: Optional[int] = None


class CategoryAnalyticsResponse(BaseModel):
    category: str
    breakdown: SentimentBreakdown
    average_confidence: float


class TrendPoint(BaseModel):
    period: str
    positive: int
    neutral: int
    negative: int
    total: int


class TrendResponse(BaseModel):
    granularity: str
    points: list[TrendPoint]


class TermPoint(BaseModel):
    term: str
    positive: int
    neutral: int
    negative: int
    total: int


class TermAnalyticsResponse(BaseModel):
    points: list[TermPoint]


class TermComparisonSide(BaseModel):
    term: str
    positive: int
    neutral: int
    negative: int
    total: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float


class TermComparisonResponse(BaseModel):
    """Current grading period vs the one immediately before it (Overview widget).

    ``current``/``previous`` are nullable: there is no active period to report
    when the month is a break and nothing has been completed yet, and no
    ``previous`` when the current period is the first in the calendar. In both
    cases ``note`` explains what the dashboard is showing.
    """

    current_term: Optional[str] = None
    previous_term: Optional[str] = None
    is_break_month: bool = False
    reference_month: str
    current: Optional[TermComparisonSide] = None
    previous: Optional[TermComparisonSide] = None
    note: str


class WordFrequencyItem(BaseModel):
    word: str
    count: int


class WordFrequencyResponse(BaseModel):
    sentiment: str
    words: list[WordFrequencyItem]


class TopCommentItem(BaseModel):
    evaluation_id: str
    category: str
    comment: str
    confidence: float


class TopCommentsResponse(BaseModel):
    kind: str  # "complaints" or "appreciations"
    items: list[TopCommentItem]
