"""Tests for Finnhub news ingestion (app.ingestion.finnhub_news).

fetch_company_news is mocked -- no real Finnhub API calls. What's under
test is our own insert/chunking/dedup logic: article + chunk writes,
skipping empty summaries, idempotent rerun, and the window-cache check
that's supposed to skip a second Finnhub call entirely.
"""

import datetime

from sqlalchemy import func, select

from app.ingestion.finnhub_news import ingest_news
from app.models import Company, NewsArticle, NewsChunk, NewsFetchLog

DATE_FROM = datetime.date(2024, 1, 1)
DATE_TO = datetime.date(2024, 1, 31)

FAKE_ARTICLE = {
    "id": 1001,
    "datetime": 1704153600,  # 2024-01-02T00:00:00Z
    "headline": "Company announces record quarter",
    "summary": "The company reported strong results.\n\nAnalysts reacted positively.",
    "url": "https://example.com/article-1001",
    "category": "company",
    "source": "Example Wire",
}


def _mock_fetch(monkeypatch, articles):
    monkeypatch.setattr("app.ingestion.finnhub_news.fetch_company_news", lambda ticker, date_from, date_to: articles)


def test_no_company_found_does_not_call_finnhub(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.ingestion.finnhub_news.fetch_company_news",
        lambda ticker, date_from, date_to: calls.append(1) or [],
    )
    ingest_news("NOPE", DATE_FROM, DATE_TO)
    assert calls == []


def test_inserts_article_and_chunks(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_fetch(monkeypatch, [FAKE_ARTICLE])

    ingest_news("TEST", DATE_FROM, DATE_TO)

    article = db_session.execute(select(NewsArticle)).scalar_one()
    assert article.source_name == "finnhub"
    assert article.external_id == "1001"
    assert article.headline == "Company announces record quarter"

    chunks = db_session.execute(select(NewsChunk).where(NewsChunk.article_id == article.id)).scalars().all()
    assert [c.chunk_text for c in chunks] == [
        "The company reported strong results.",
        "Analysts reacted positively.",
    ]


def test_skips_articles_with_no_summary(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_fetch(monkeypatch, [{**FAKE_ARTICLE, "summary": ""}])

    ingest_news("TEST", DATE_FROM, DATE_TO)

    assert db_session.execute(select(func.count()).select_from(NewsArticle)).scalar_one() == 0


def test_records_a_fetch_log_entry(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_fetch(monkeypatch, [FAKE_ARTICLE])

    ingest_news("TEST", DATE_FROM, DATE_TO)

    log = db_session.execute(select(NewsFetchLog)).scalar_one()
    assert log.date_from == DATE_FROM
    assert log.date_to == DATE_TO


def test_second_call_within_an_already_fetched_window_skips_finnhub(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_fetch(monkeypatch, [FAKE_ARTICLE])
    ingest_news("TEST", DATE_FROM, DATE_TO)

    calls = []
    monkeypatch.setattr(
        "app.ingestion.finnhub_news.fetch_company_news",
        lambda ticker, date_from, date_to: calls.append(1) or [],
    )
    # A narrower window fully inside the one already logged.
    ingest_news("TEST", datetime.date(2024, 1, 10), datetime.date(2024, 1, 20))

    assert calls == []


def test_window_only_partially_overlapping_still_calls_finnhub(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_fetch(monkeypatch, [FAKE_ARTICLE])
    ingest_news("TEST", DATE_FROM, DATE_TO)

    calls = []
    monkeypatch.setattr(
        "app.ingestion.finnhub_news.fetch_company_news",
        lambda ticker, date_from, date_to: calls.append(1) or [],
    )
    # Overlaps but extends past the already-logged window -- not fully covered.
    ingest_news("TEST", datetime.date(2024, 1, 20), datetime.date(2024, 2, 20))

    assert calls == [1]


def test_rerunning_the_exact_same_window_is_idempotent_for_article_rows(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_fetch(monkeypatch, [FAKE_ARTICLE])
    ingest_news("TEST", DATE_FROM, DATE_TO)

    # Force past the window-cache skip to exercise on_conflict_do_nothing directly.
    db_session.execute(NewsFetchLog.__table__.delete())
    db_session.commit()
    ingest_news("TEST", DATE_FROM, DATE_TO)

    assert db_session.execute(select(func.count()).select_from(NewsArticle)).scalar_one() == 1
