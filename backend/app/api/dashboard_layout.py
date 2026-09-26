"""Shared dashboard layout: admin writes the widget geometry, everyone else reads it.

Two endpoints, deliberately asymmetric:

* ``GET  /dashboard-layout/{name}``  -- faculty and administrators
  (``require_staff``). Everyone who renders a dashboard needs the saved
  geometry to render it, and the document contains nothing but widget ids and
  sizes (no feedback, no user data). Students are refused: they have no
  dashboard to lay out.
* ``PUT  /dashboard-layout/{name}``  -- administrators only (``require_admin``).
  This is the whole access-control surface of the editing feature, and it is
  enforced server-side rather than by hiding a button: a faculty member who
  crafts the request by hand gets a 403.

A missing layout is not an error. The first render of any page has nothing
saved yet, so GET returns an empty widget map and the frontend applies the
built-in default layout. That keeps the read path total -- every dashboard
works before anyone has opened the editor.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_staff
from app.core.database import get_db
from app.core.time import utcnow_naive
from app.models.dashboard_layout import DashboardLayout
from app.schemas.dashboard_layout import LayoutOut, LayoutSave, WidgetSize
from app.utils.logger import logger

router = APIRouter(prefix="/dashboard-layout", tags=["Dashboard Layout"])


def _row_to_out(row: DashboardLayout) -> LayoutOut:
    """Parse the stored JSON document back into the response shape.

    A malformed document is treated as "no saved layout" rather than a 500:
    the layout is a presentation preference, so a corrupt row must degrade to
    the default layout rather than take a dashboard down for every user.
    """
    try:
        raw = json.loads(row.payload)
        if not isinstance(raw, dict):
            raise ValueError("payload is not an object")
        widgets = {
            str(k): WidgetSize(**v) for k, v in raw.items() if isinstance(v, dict)
        }
    except (ValueError, TypeError, ValidationError) as exc:
        logger.warning(
            "Dashboard layout %s has an unreadable payload, falling back to "
            "the default layout: %s",
            row.name,
            exc,
        )
        widgets = {}
    return LayoutOut(
        name=row.name,
        widgets=widgets,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@router.get("/{name}", response_model=LayoutOut)
def get_dashboard_layout(
    name: str, db: Session = Depends(get_db), _user=Depends(require_staff)
) -> LayoutOut:
    """Return the saved layout for ``name``, or an empty one if never saved.

    Readable by faculty and administrators: faculty render the finalized
    layout, so they need the geometry. Students are refused -- the dashboards
    this geometry applies to are staff surfaces, and a student has no
    dashboard to lay out.

    The document contains only widget ids and sizes, so serving it to faculty
    discloses no feedback data.
    """
    row = db.query(DashboardLayout).filter(DashboardLayout.name == name).first()
    if row is None:
        # No row yet: not an error, just the default layout.
        return LayoutOut(
            name=name, widgets={}, updated_at=utcnow_naive()
        )
    return _row_to_out(row)


@router.put("/{name}", response_model=LayoutOut)
def save_dashboard_layout(
    name: str,
    payload: LayoutSave,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> LayoutOut:
    """Replace the layout for ``name``. Administrators only.

    The body ``name`` must match the path ``name``; allowing them to differ
    would make it possible to write to a layout other than the one addressed,
    which is a confusing way to lose an edit.
    """
    if payload.name != name.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Layout name in the body must match the name in the path.",
        )

    document = {
        key: {"w": size.w, "h": size.h, "order": size.order}
        for key, size in payload.widgets.items()
    }
    row = db.query(DashboardLayout).filter(DashboardLayout.name == name).first()
    if row is None:
        row = DashboardLayout(
            name=name,
            payload=json.dumps(document),
            updated_by=current_user.id,
        )
        db.add(row)
    else:
        row.payload = json.dumps(document)
        row.updated_by = current_user.id
    db.commit()
    db.refresh(row)
    logger.info("Dashboard layout %s saved (%d widgets)", name, len(document))
    return _row_to_out(row)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def reset_dashboard_layout(
    name: str, db: Session = Depends(get_db), _user=Depends(require_admin)
) -> None:
    """Delete the saved layout so the page falls back to its default.

    The "Reset to default" button in the editor. Deleting rather than saving an
    empty document means a later "no saved layout" is genuinely the default and
    not a stale empty state.
    """
    row = db.query(DashboardLayout).filter(DashboardLayout.name == name).first()
    if row is not None:
        db.delete(row)
        db.commit()
        logger.info("Dashboard layout %s reset to default", name)
