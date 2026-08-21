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
    comment: str = Field(min_length=3, max_length=5000)  # Kept for backward compatibility
    evaluatee: str | None = None
    strengths: str | None = None
    areas_for_improvement: str | None = None
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
