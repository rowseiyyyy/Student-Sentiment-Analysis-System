"""
SQLAlchemy engine / session management.
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

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
