"""Shared pytest fixtures.

Tests run against a dedicated `earnings_timeline_test` database, never
the dev one — the DATABASE_URL override below has to happen before
`app.db` (and anything importing it) is loaded for the first time, since
the engine is built at import time.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_dev_database_url = os.environ["DATABASE_URL"]
_test_db_name = "earnings_timeline_test"
TEST_DATABASE_URL = _dev_database_url.rsplit("/", 1)[0] + f"/{_test_db_name}"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402, F401 — registers every table on Base.metadata
    Company,
    CompanyAlias,
    Filing,
    FilingChunk,
    FinancialMetric,
    NewsArticle,
    NewsChunk,
    NewsFetchLog,
    PriceHistory,
)


def _ensure_test_database_exists() -> None:
    # CREATE DATABASE can't run inside a transaction block.
    admin_engine = create_engine(_dev_database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": _test_db_name}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_test_db_name}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    _ensure_test_database_exists()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate every table before each test so tests never see rows left
    behind by another test. Ingestion/derivation functions under test open
    their own SessionLocal() and commit internally, so transaction-rollback
    isolation doesn't apply here — truncation is the simpler correct tool.
    """
    with engine.begin() as conn:
        table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()
