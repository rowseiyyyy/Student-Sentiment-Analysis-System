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


class CourseSentimentPoint(BaseModel):
    """One course's aggregate for the "Sentiment by Courses" chart.

    ``sentiment_score`` is a net score on a -100..+100 scale, computed as
    ``(positive - negative) / total * 100``: +100 means the course's feedback
    was entirely positive, -100 entirely negative, and 0 means positives and
    negatives cancel out. Neutral submissions still count toward ``total``
    (and therefore shrink the score toward 0) so a course cannot look
    perfectly positive off a single submission.
    """

    course: str
    positive: int
    neutral: int
    negative: int
    total: int
    sentiment_score: float


class CourseAnalyticsResponse(BaseModel):
    # Rows arrive sorted by descending sentiment_score, which is exactly the
    # order the horizontal bar chart plots (best course at the top).
    points: list[CourseSentimentPoint]


class RatingBandPoint(BaseModel):
    """One band of the 1-5 Likert histogram, with the sentiment split of the
    submissions that landed in it (so the chart can stack)."""

    band: int
    label: str
    positive: int
    neutral: int
    negative: int
    total: int


class RatingDistributionResponse(BaseModel):
    # All five bands are always present, zero-filled, so the x-axis stays 1-5.
    points: list[RatingBandPoint]
    # Submissions that carried a Likert answer (comment-only rows are excluded).
    total: int
    # Mean of the raw 1-5 scores, or None when nothing was rated.
    average: Optional[float] = None


class AspectAveragePoint(BaseModel):
    """Mean score for one rating aspect plus how many students answered it."""

    aspect: str
    label: str
    average: float
    responses: int


class AspectAveragesResponse(BaseModel):
    # Sorted by descending average, which is the order the horizontal bar chart
    # plots (strongest aspect at the top, weakest at the bottom).
    points: list[AspectAveragePoint]
    total: int


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
