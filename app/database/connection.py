"""Shared SQLAlchemy engine (connection pool) for the application."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings

engine: Engine = create_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,  # replace connections the server has dropped
)


def check_connection() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
