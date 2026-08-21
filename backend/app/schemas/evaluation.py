from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.evaluation import EvaluationCategory
from app.schemas.prediction import PredictionOut


class StudentInfo(BaseModel):
    student_id: str | None = None
    course: str | None = None
    year_level: str | None = None
    full_name: str | None = None


class EvaluationCreate(BaseModel):
    category: EvaluationCategory
    # Optional: a student may submit only Likert ratings, or only
    # strengths/areas_for_improvement, without free-text `comment`. The API
    # layer (app.api.evaluation.submit_evaluation) enforces that at least
    # one of comment / strengths / areas_for_improvement / ratings is
    # present — making `comment` required here would silently defeat that
    # check with an early 422 before the handler ever runs.
    comment: str | None = Field(default=None, max_length=5000)
    evaluatee: str | None = None
    strengths: str | None = None
    areas_for_improvement: str | None = None
    # Likert-scale ratings: mapping of question/aspect -> 1-5 score.
    ratings: dict[str, Any] | None = None
    # Student info for anonymous submissions (will be saved to User record)
    student_id: str | None = None
    course: str | None = None
    year_level: str | None = None


class EvaluationOut(BaseModel):
    id: str
    user_id: str | None
    category: EvaluationCategory
    comment: str
    evaluatee: str | None = None
    strengths: str | None = None
    areas_for_improvement: str | None = None
    ratings: dict[str, Any] | None = None
    sentiment: str | None = None
    # Likert-derived classification, independent of the text sentiment
    # `prediction` below. Present whenever `ratings` were submitted.
    likert_sentiment: str | None = None
    likert_average: float | None = None
    created_at: datetime
    prediction: PredictionOut | None = None
    student: StudentInfo | None = None

    class Config:
        from_attributes = True


class EvaluationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[EvaluationOut]


class ImportRowError(BaseModel):
    row: int
    comment: str
    errors: list[str]


class ImportResultResponse(BaseModel):
    total_rows: int
    imported: int
    failed: int
    errors: list[ImportRowError]