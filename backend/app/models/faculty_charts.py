import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FacultyChartVisibility(Base):
    """Single shared row: which analytics charts faculty accounts may see.

    The visibility setting is global, not per-user: an administrator decides
    which of the faculty dashboard's charts are shared with the whole faculty
    role, and every faculty account gets the same answer. There is exactly one
    current setting, so this table holds at most one row (callers always read
    the first row).

    ``payload`` is a JSON document ``{"<chart-key>": true|false}``. Keys absent
    from the document fall back to the registry's per-chart default
    (``app.services.faculty_charts.FACULTY_CHARTS``), which is what lets a
    chart added in a later release default to hidden without a migration: the
    new key simply has no stored value yet.

    Storing the map as JSON rather than as columns keeps the table stable as
    charts are added or renamed -- a chart is a key, not a migration.
    """

    __tablename__ = "faculty_chart_visibility"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # JSON: {"sentiment_split": true, "rating_distribution": false, ...}
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
