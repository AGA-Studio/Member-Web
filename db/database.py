"""Database connection: engine, table creation and per-request session."""

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from core.config import settings

DATABASE_URL = settings.effective_database_url

# SQLite needs this flag to be used from FastAPI's worker threads.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)


def create_db_and_tables() -> None:
    # Importing the models registers their tables in SQLModel.metadata.
    import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session
