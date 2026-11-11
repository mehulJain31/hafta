"""Test setup: a throwaway DB and a dummy API key so importing `agent` (which
constructs the Anthropic client at import) doesn't try to resolve credentials.
Claude itself is always monkeypatched in the flow tests — no network calls."""

import os
import tempfile

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
os.environ.setdefault("CLOVEFI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("LENDER_NAME", "Test Credit Union")
os.environ.setdefault("DEFAULT_TIMEZONE", "UTC")

import pytest  # noqa: E402
from sqlmodel import SQLModel, Session  # noqa: E402

import db  # noqa: E402


@pytest.fixture
def session():
    SQLModel.metadata.drop_all(db.engine)
    db.create_db_and_tables()  # create + seed one CU + policy
    with Session(db.engine) as s:
        yield s
