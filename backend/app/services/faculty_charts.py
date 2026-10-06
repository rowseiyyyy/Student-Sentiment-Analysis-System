"""Registry and resolution for the admin-managed faculty chart visibility.

The registry is the single source of truth for *which* analytics charts are
"faculty charts": the admin's "Manage faculty access" panel lists them, the
faculty dashboard renders exactly the enabled ones, and the analytics API
gates the endpoints that back them.

Defaults
--------
``default=True`` -- every chart that existed when this feature shipped
(first deploy): the setting has never been saved, so nothing may disappear
under anyone's feet. This is why the table starts out EMPTY rather than
pre-seeded: "no row" means "use the registry defaults", and the registry
already says the current charts are visible.

``default=False`` -- every chart added afterwards. A new chart stays hidden
from faculty until an administrator explicitly turns it on, so a release can
land new panels without silently widening what faculty can read.

Saving stores an explicit value for every registry key, so after the first
save the stored map (not the defaults) decides; keys missing from a stored
map (e.g. a chart added after the last save) still fall back to the default.
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.faculty_charts import FacultyChartVisibility
from app.utils.logger import logger

# key -> (label shown in the admin panel, default visibility)
FACULTY_CHARTS: dict[str, tuple[str, bool]] = {
    "sentiment_split": ("Sentiment Split", True),
    "rating_distribution": ("Rating Distribution", True),
    "aspect_averages": ("Average by Aspect", True),
    "sentiment_courses": ("Sentiment by Courses", True),
    "top_comments": ("Top Comments", True),
}


def default_visibility() -> dict[str, bool]:
    """The registry defaults: the answer when nothing has ever been saved."""
    return {key: default for key, (_label, default) in FACULTY_CHARTS.items()}


def _stored_payload(db: Session) -> dict[str, Any] | None:
    """The raw stored map, or ``None`` when never saved / unreadable."""
    row = db.query(FacultyChartVisibility).first()
    if row is None:
        return None
    try:
        raw = json.loads(row.payload)
        if not isinstance(raw, dict):
            raise ValueError("payload is not an object")
        return raw
    except (ValueError, TypeError) as exc:
        # A corrupt row degrades to the defaults rather than 500-ing every
        # analytics request that passes through the gate. Same philosophy as
        # the dashboard layout reader.
        logger.warning(
            "Faculty chart visibility payload is unreadable, falling back to "
            "the registry defaults: %s",
            exc,
        )
        return None


def resolve(db: Session) -> dict[str, bool]:
    """Final visibility for every registry chart, stored value over default.

    Unknown keys in the stored payload are ignored (the registry is the
    source of truth), and a registry key with no stored value falls back to
    its default -- so a chart added in a later release defaults to hidden.
    """
    stored = _stored_payload(db) or {}
    return {
        key: bool(stored[key]) if key in stored else default
        for key, (_label, default) in FACULTY_CHARTS.items()
    }


def is_enabled(db: Session, chart_key: str) -> bool:
    """Visibility of one chart. Unknown keys are simply not enabled."""
    return resolve(db).get(chart_key, False)
