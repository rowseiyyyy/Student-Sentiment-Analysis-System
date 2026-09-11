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
    "pool_recycle": 3600,
    "echo": False,
}

# Match the raw PyMySQL working pattern by handing the DBAPI the same
# neutral SSL context object shape that `pymysql.connect(..., ssl={})`
# accepts, rather than wrapping it inside an extra nested `ssl` key.
database_url = settings.DATABASE_URL

# Add SSL for MySQL connections (required by most cloud providers).
if "mysql" in database_url:
    engine_kwargs["connect_args"] = {
        "ssl": {}
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
