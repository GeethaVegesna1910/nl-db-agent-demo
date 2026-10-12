"""Shared SQLAlchemy engines (connection pools) for the application.

engine        full access, for the application's own work (chat history, setup).
agent_engine  read-only login, for running SQL written by the LLM.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.config import settings

engine: Engine = create_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,  # replace connections the server has dropped
)

# Same host, port and database as above, but logged in as the restricted role.
agent_engine: Engine = create_engine(
    make_url(settings.database_url).set(
        username=settings.agent_db_user, password=settings.agent_db_password
    ),
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
)


def check_connection() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
