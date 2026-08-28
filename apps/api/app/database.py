"""Database engine and session configuration."""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Use environment variable directly to avoid circular imports with config
DATABASE_URL = os.environ.get("DATABASE_URL", "")

Base = declarative_base()

# Engine and SessionLocal are created lazily or when DATABASE_URL is available
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create SQLAlchemy engine."""
    global _engine
    if _engine is None:
        database_url = os.environ.get("DATABASE_URL", DATABASE_URL)
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable not set")
        _engine = create_engine(database_url, pool_pre_ping=True)
    return _engine


def get_session_local():
    """Get or create session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """Provide database session per request."""
    session_local = get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()
