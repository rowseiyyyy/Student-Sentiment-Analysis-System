from datetime import datetime

from pydantic import BaseModel, Field

# One entry per registry chart; the cap only has to outgrow the registry by a
# wide margin so a future chart never trips it.
MAX_CHARTS = 50


class FacultyChartStatus(BaseModel):
    """One faculty chart's identity and its current visibility."""

    key: str
    label: str
    visible: bool


class FacultyChartsOut(BaseModel):
    """The full visibility map, in registry order.

    Readable by faculty as well as administrators: the flags are metadata
    (which panels are shared), not feedback data, and the faculty dashboard
    needs them to decide what to render. The chart *data* endpoints are the
    ones gated server-side by these same flags.
    """

    charts: list[FacultyChartStatus]
    updated_at: datetime | None = None


class FacultyChartsSave(BaseModel):
    """Full replacement of the visibility map, sent by the admin's panel.

    The whole map is replaced rather than merged: the admin's editor always
    holds the current server state, so a merge would leave keys for charts
    that have since been removed behind forever. Keys absent from the body
    fall back to their registry default on read.
    """

    charts: dict[str, bool] = Field(max_length=MAX_CHARTS)
