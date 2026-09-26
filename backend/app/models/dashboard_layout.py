import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DashboardLayout(Base):
    """A named, shared dashboard layout: per-widget width/height.

    The layout is the "house style" of the reporting pages. An administrator
    resizes a chart or card here, and every other admin, faculty member and
    student then sees that arrangement -- there is exactly one current layout
    per ``name`` (enforced by a unique constraint in the migration), so the
    saved geometry is a single source of truth rather than a per-user
    preference.

    Storing geometry as a JSON document in ``payload`` rather than as columns
    keeps this table stable as widgets are added: a new widget is a new key in
    the document, not a migration. The key format is ``"<tab>:<widget-id>"``,
    e.g. ``"analytics:chart-host-rating-by-dept"``.

    Width is stored as a small integer *grid-unit* count rather than pixels.
    That is what lets a saved layout survive a change to the page container's
    max-width: the stored value means "span N of whatever the grid currently
    is", so widening the container re-flows the layout instead of leaving
    stranded fixed-width columns.
    """

    __tablename__ = "dashboard_layouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # "admin_overview" / "admin_analytics" / "faculty_dashboard" etc.
    name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # JSON: {"<tab>:<widget-id>": {"w": 2, "h": 320}, ...}
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
