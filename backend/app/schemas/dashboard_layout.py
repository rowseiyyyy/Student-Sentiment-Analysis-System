from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

# Geometry bounds. These are deliberately wider than the UI's own limits: the
# server is the last line of defence against a hand-crafted payload storing a
# value that would render unusably (a zero-height chart, a 100000px column),
# while the frontend clamps to a tighter, design-driven range.
MIN_W, MAX_W = 1, 4
MIN_H, MAX_H = 120, 1200
# A layout is a page of widgets; cap the key count so one request cannot be
# used to write an unbounded document.
MAX_WIDGETS = 200
MAX_KEY_LEN = 120


class WidgetSize(BaseModel):
    """Geometry for a single widget.

    ``w`` is a grid-unit count (how many of the page's current columns the
    widget spans), not pixels. Storing units rather than pixels is what lets a
    saved layout survive a change to the page container's max-width.
    """

    w: int = Field(ge=MIN_W, le=MAX_W)
    h: int = Field(ge=MIN_H, le=MAX_H)

    @field_validator("h")
    @classmethod
    def _height_multiple_of_10(cls, v: int) -> int:
        # Round to a 10px step so a drag-to-resize gesture produces a tidy
        # stored value instead of an arbitrary pixel.
        return int(round(v / 10.0) * 10)


class LayoutSave(BaseModel):
    """Full replacement of one named layout.

    The whole document is replaced rather than merged: the admin's editor
    always holds the current server state, so a merge would leave keys for
    widgets that have since been deleted behind forever.

    The widget-count and key checks below raise ``PydanticCustomError``
    rather than a bare ``ValueError`` on purpose. FastAPI renders a
    ``RequestValidationError`` by JSON-serialising the error context, and
    pydantic puts a raised ``ValueError`` object into that context -- which is
    not serialisable, so a plain ``ValueError`` here turns a 422 into a 500.
    """

    name: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_\-]+$")
    widgets: dict[str, WidgetSize]

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("widgets")
    @classmethod
    def _check_widgets(cls, v: dict[str, WidgetSize]) -> dict[str, WidgetSize]:
        if len(v) > MAX_WIDGETS:
            raise PydanticCustomError(
                "too_many_widgets", "too many widgets in one layout (max {max})", {"max": MAX_WIDGETS}
            )
        for key in v:
            if not key or len(key) > MAX_KEY_LEN:
                raise PydanticCustomError(
                    "invalid_widget_key", "invalid widget key: {key!r}", {"key": key}
                )
        return v


class LayoutOut(BaseModel):
    name: str
    widgets: dict[str, WidgetSize]
    updated_at: datetime
    updated_by: str | None = None
