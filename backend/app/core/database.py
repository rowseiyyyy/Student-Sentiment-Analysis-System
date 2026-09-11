"""
SQLAlchemy engine / session management.
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# Configure engine based on database type
engine_kwargs = {
    "pool_pre_ping": True,
    "pool_recycle": 3600,
    "echo": False,
}

# Strip the unsupported SSL URL query key before handing the DSN to
# PyMySQL. This key is a documentation/control-plane hint in config,
# but PyMySQL/SQLAlchemy coordinate the actual TLS handshake via the
# connection args payload rather than through the query namespace.
database_url = settings.DATABASE_URL
connection_url = make_url(database_url)
if connection_url.drivername == "mysql+pymysql" and connection_url.query.get("ssl-mode") == "REQUIRED":
    cleaned_query = dict(connection_url.query)
    cleaned_query.pop("ssl-mode", None)
    connection_url = URL.create(
        drivername=connection_url.drivername,
        username=connection_url.username,
        password=connection_url.password,
        host=connection_url.host,
        port=connection_url.port,
        database=connection_url.database,
        query=cleaned_query,
    )
    database_url = str(connection_url)

# Add SSL for MySQL connections (required by most cloud providers)
if "mysql" in database_url:
    engine_kwargs["connect_args"] = {
        "ssl": {"check_hostname": False}
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
