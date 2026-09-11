"""
SQLAlchemy engine / session management.
"""
import logging
from functools import wraps
from typing import Any, Callable, Generator

from sqlalchemy import create_engine
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

# Errors that indicate a dropped / transiently-failed connection.
# Aiven's TLS proxy occasionally kills a connection *mid-query* (MySQL
# errors 2006 "server has gone away" and 2013 "lost connection during
# query"). pool_recycle + pool_pre_ping handle stale-checkout cases, but a
# drop that happens while a long read is streaming cannot be prevented
# client-side — it needs a retry.
_TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError, DisconnectionError)


def retry_on_disconnect(*, attempts: int = 2) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry a read-only FastAPI endpoint when its DB connection drops.

    On a transient connection failure the session is rolled back (which
    frees / recycles the dead pooled connection) and the handler body runs
    again, checking out a fresh connection from the pool. Only safe for
    idempotent (read-only) handlers — never wrap a mutating endpoint with this.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except _TRANSIENT_DB_ERRORS as exc:
                    last_error = exc
                    if attempt + 1 >= attempts:
                        break
                    logger.warning(
                        "Transient DB connection error on %s (attempt %d/%d): %s",
                        fn.__name__, attempt + 1, attempts, exc,
                    )
                    db = kwargs.get("db")
                    if db is None:
                        db = next((a for a in args if isinstance(a, Session)), None)
                    if db is not None:
                        try:
                            db.rollback()
                        except Exception:  # noqa: BLE001 - best-effort recovery
                            pass
            raise last_error  # type: ignore[misc]

        return wrapper

    return decorator

# Configure engine based on database type
engine_kwargs = {
    "pool_pre_ping": True,
    # Aiven's TLS proxy silently drops connections that sit idle in the
    # pool (surfacing later as 2006 "MySQL server has gone away" / SSL EOF
    # mid-query). Keep connections very short-lived — recycling every two
    # minutes is cheap compared to serving a request on a dead one.
    "pool_recycle": 120,
    "echo": False,
}

# Match the raw PyMySQL working pattern by sending the SSL context as
# the dialect's native connect-args object instead of encoding the TLS
# hint into the URL query string. The DBAPI sees the nested `ssl` object
# exactly as `pymysql.connect(..., ssl={'ssl': {}})` does.
database_url = settings.DATABASE_URL

# Add SSL for MySQL connections (required by most cloud providers)
if "mysql" in database_url:
    engine_kwargs["connect_args"] = {
        "ssl": {"ssl": {}}
    }

engine = create_engine(database_url, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


def get_db() -> Generator:
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
