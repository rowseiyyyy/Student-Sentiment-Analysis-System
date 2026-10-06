"""Faculty chart visibility: admin writes the global map, everyone reads it.

Two endpoints, deliberately asymmetric -- the same shape as the shared
dashboard layout this feature deliberately mirrors:

* ``GET  /analytics/faculty-charts`` -- faculty and administrators
  (``require_staff``). The faculty dashboard needs the map to know which
  panels to render and which data endpoints to call; an administrator needs
  it to show the badges and pre-check the panel. It is metadata only (keys,
  labels, booleans), so serving it to faculty discloses no feedback data.
* ``PUT  /analytics/faculty-charts`` -- administrators only
  (``require_admin``), enforced server-side: a faculty member who crafts the
  request by hand gets a 403.

The map is GLOBAL for all faculty accounts (one row in the table), and the
read path is total: a missing row means "registry defaults", never an error.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_staff
from app.core.database import get_db
from app.models.faculty_charts import FacultyChartVisibility
from app.models.user import User
from app.schemas.faculty_charts import FacultyChartStatus, FacultyChartsOut, FacultyChartsSave
from app.services import faculty_charts as visibility
from app.utils.logger import logger

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _out(db: Session) -> FacultyChartsOut:
    """Registry-ordered statuses plus the row's timestamp (if any)."""
    resolved = visibility.resolve(db)
    row = db.query(FacultyChartVisibility).first()
    return FacultyChartsOut(
        charts=[
            FacultyChartStatus(key=key, label=visibility.FACULTY_CHARTS[key][0], visible=visible)
            for key, visible in resolved.items()
        ],
        updated_at=row.updated_at if row is not None else None,
    )


@router.get("/faculty-charts", response_model=FacultyChartsOut)
def get_faculty_charts(db: Session = Depends(get_db), _user: User = Depends(require_staff)):
    """The current visibility map (registry defaults when never saved)."""
    return _out(db)


@router.put("/faculty-charts", response_model=FacultyChartsOut)
def save_faculty_charts(
    payload: FacultyChartsSave,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Replace the visibility map. Administrators only.

    Unknown keys are rejected rather than silently dropped: a typo'd key
    would otherwise look like a successful save while leaving the real chart
    untouched.
    """
    unknown = sorted(set(payload.charts) - set(visibility.FACULTY_CHARTS))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown faculty chart key(s): " + ", ".join(unknown),
        )

    # Rebuilt key by key so only registry keys ever reach the stored document.
    document = {key: bool(payload.charts[key]) for key in visibility.FACULTY_CHARTS if key in payload.charts}
    row = db.query(FacultyChartVisibility).first()
    if row is None:
        row = FacultyChartVisibility(payload=json.dumps(document), updated_by=current_user.id)
        db.add(row)
    else:
        row.payload = json.dumps(document)
        row.updated_by = current_user.id
    db.commit()
    db.refresh(row)
    logger.info(
        "Faculty chart visibility saved by %s: %s",
        current_user.email,
        {k: v for k, v in document.items() if not v} or "all visible",
    )
    return _out(db)
