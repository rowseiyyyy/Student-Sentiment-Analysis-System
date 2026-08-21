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
