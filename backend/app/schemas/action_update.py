from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.action_update import ActionStatus
from app.models.evaluation import EvaluationCategory


class ActionUpdateCreate(BaseModel):
    category: EvaluationCategory
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=10)
    status: ActionStatus = ActionStatus.ACKNOWLEDGED
    resolution_note: str | None = None
    # Admin-only bookkeeping (e.g. "feedback spike, Jul 2026"). Never
    # rendered on the public bulletin.
    internal_reference: str | None = Field(default=None, max_length=200)


class ActionUpdateUpdate(BaseModel):
    category: EvaluationCategory | None = None
    title: str | None = Field(default=None, min_length=3, max_length=200)
    summary: str | None = Field(default=None, min_length=10)
    status: ActionStatus | None = None
    resolution_note: str | None = None
    internal_reference: str | None = Field(default=None, max_length=200)


class ActionUpdateOut(BaseModel):
    id: UUID
    category: EvaluationCategory
    title: str
    summary: str
    status: ActionStatus
    resolution_note: str | None
    internal_reference: str | None
    date_posted: datetime
    date_updated: datetime

    model_config = {"from_attributes": True}


class PublicActionUpdateOut(BaseModel):
    """Public projection — deliberately excludes internal_reference and
    any identifier that could link the post back to a submission."""
    id: UUID
    category: EvaluationCategory
    title: str
    summary: str
    status: ActionStatus
    resolution_note: str | None
    date_posted: datetime

    model_config = {"from_attributes": True}


class PublicCategoryStat(BaseModel):
    category: str
    negative_this_month: int
    total_this_month: int


class PublicBulletinResponse(BaseModel):
    posts: list[PublicActionUpdateOut]
    category_stats: list[PublicCategoryStat]
