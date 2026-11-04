"""Database engine, session and time helpers.

SQLite for local dev (single file, zero setup); the SQLModel/SQLAlchemy layer
keeps a later move to Postgres to a connection-string change. All timestamps are
stored timezone-aware in UTC — see now_utc().
"""

import os
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

DB_PATH = os.getenv("CLOVEFI_DB", "clovefi.db")
# check_same_thread=False: FastAPI serves requests from a threadpool.
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def now_utc() -> datetime:
    """A timezone-aware UTC instant. Never use naive datetime.now()/utcnow()."""
    return datetime.now(timezone.utc)


def create_db_and_tables() -> None:
    import models  # noqa: F401  (registers the tables on SQLModel.metadata)

    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
