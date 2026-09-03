from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from app.models.evaluation import EvaluationCategory
from app.schemas.prediction import PredictionOut

# Legacy/singular category names still sent by older clients and by the
# admin/faculty dashboard chart filters ("Faculty", "Payment", and the
# lowercase student-form keys). Map them onto the canonical enum values so
# submissions and analytics queries don't fail with a 422
# ("Input should be 'Professors', 'Staff', 'Payments' or 'Facilities'").
_CATEGORY_ALIASES: dict[str, str] = {
    "faculty": "Professors",
    "professor": "Professors",
    "professors": "Professors",
    "staff": "Staff",
    "facilities": "Facilities",
    "payment": "Payments",
    "payments": "Payments",
}


def normalize_category(value: Any) -> Any:
    """Coerce legacy/loose category strings onto canonical enum values."""
    if isinstance(value, str):
        return _CATEGORY_ALIASES.get(value.strip().lower(), value.strip())
    return value


# Reusable annotated type: works both in request bodies (EvaluationCreate)
# and as FastAPI query parameters (analytics endpoints).
NormalizedCategory = Annotated[EvaluationCategory, BeforeValidator(normalize_category)]


class StudentInfo(BaseModel):
    student_id: str | None = None
    course: str | None = None
    year_level: str | None = None
    full_name: str | None = None


class EvaluationCreate(BaseModel):
    # Accepts legacy/loose names ("Faculty", "Payment", lowercase keys) and
    # normalizes them onto the canonical enum values — see normalize_category.
    category: NormalizedCategory
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