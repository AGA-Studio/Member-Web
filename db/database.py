"""Database connection: engine, connectivity check and per-request session.

The schema is managed by Alembic (migrations/), not by the app.
"""

from collections.abc import Generator

from sqlalchemy import text
from sqlmodel import Session, create_engine

from core.config import settings

DATABASE_URL = settings.effective_database_url

# SQLite needs this flag to be used from FastAPI's worker threads.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)


def check_database_connection() -> None:
    """Fail fast at startup if the database is unreachable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session
