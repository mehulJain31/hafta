"""Database engine, session, seeding and time helpers.

SQLite for local dev (`clovefi.db`); the SQLModel/SQLAlchemy layer keeps a later
move to Postgres to a connection-string change. All timestamps are stored
timezone-aware in UTC — see now_utc().
"""

import os
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

DB_PATH = os.getenv("CLOVEFI_DB", "clovefi.db")
# check_same_thread=False: FastAPI serves requests from a threadpool.
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

LENDER_NAME = os.getenv("LENDER_NAME", "State Bank of Elytra")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "America/Los_Angeles")


def now_utc() -> datetime:
    """A timezone-aware UTC instant. Never use naive datetime.now()/utcnow()."""
    return datetime.now(timezone.utc)


def create_db_and_tables() -> None:
    import models  # noqa: F401  (registers the tables on SQLModel.metadata)

    SQLModel.metadata.create_all(engine)
    _seed()


def _seed() -> None:
    """Seed one credit union + policy so the app runs with no manual setup."""
    from models import CreditUnion, CuPolicy

    with Session(engine) as session:
        if session.exec(select(CreditUnion)).first() is not None:
            return
        cu = CreditUnion(name=LENDER_NAME, timezone=DEFAULT_TIMEZONE)
        session.add(cu)
        session.commit()
        session.refresh(cu)
        session.add(CuPolicy(
            credit_union_id=cu.id,
            allowed_plan_types=["FULL", "SPLIT"],
            max_installments=4,
            installment_interval="monthly",
            max_extension_days=0,
            min_installment_cents=2500,
            auto_escalate_reasons=["BANKRUPTCY"],
            first_payment_rule="on_due_date",
        ))
        session.commit()


def get_session():
    with Session(engine) as session:
        yield session
