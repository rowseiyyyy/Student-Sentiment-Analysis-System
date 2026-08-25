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
    # share_your_thoughts, without free-text `comment`. The API layer
    # (app.api.evaluation.submit_evaluation) enforces that at least one
    # of comment / share_your_thoughts / ratings is present — making
    # `comment` required here would silently defeat that check with an
    # early 422 before the handler ever runs.
    comment: str | None = Field(default=None, max_length=5000)
    evaluatee: str | None = None
    share_your_thoughts: str | None = None
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
    share_your_thoughts: str | None = None
    ratings: dict[str, Any] | None = None
    sentiment: str | None = None
    likert_sentiment: str | None = None
    likert_average: float | None = None
    # Likert-vs-sentiment mismatch flag (see app.services.mismatch).
    # False/"none" whenever ratings or comment weren't both submitted.
    is_mismatch: bool = False
    mismatch_type: str = "none"
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


class BulkDeleteRequest(BaseModel):
    # Ids of evaluations to delete. Must contain at least one entry -
    # the API layer also checks this, but enforcing it here gives a
    # clean 422 instead of a 400 for the trivial empty-list case.
    ids: list[str] = Field(min_length=1)


class BulkDeleteResponse(BaseModel):
    deleted_count: int
    not_found: list[str]


class ImportRowError(BaseModel):
    row: int
    comment: str
    errors: list[str]


class ImportResultResponse(BaseModel):
    total_rows: int
    imported: int
    failed: int
    errors: list[ImportRowError]