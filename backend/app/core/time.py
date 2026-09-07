"""Time helpers for database columns that store naive UTC datetimes."""
from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Return current UTC time without timezone metadata for legacy DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)