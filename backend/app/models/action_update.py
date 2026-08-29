import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.evaluation import EvaluationCategory


class ActionStatus(str, enum.Enum):
    """Lifecycle of an "Action Taken" bulletin post. Rendered publicly so
    students can see that feedback leads to action."""
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class ActionUpdate(Base):
    """Aggregate, public-facing "Action Taken" bulletin post.

    Created by admins in response to feedback trends (e.g. a spike of
    negative Facilities comments). Deliberately stores NO evaluation ids,
    student ids, or raw comment text: the public endpoint renders only
    category / title / summary / status / resolution note. The optional
    ``internal_reference`` is for admin bookkeeping and is never exposed
    publicly.
    """
    __tablename__ = "action_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    category: Mapped[EvaluationCategory] = mapped_column(Enum(EvaluationCategory), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus), nullable=False, default=ActionStatus.ACKNOWLEDGED
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_posted: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
