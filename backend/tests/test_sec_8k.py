"""Tests for bulk 8-K ingestion (app.ingestion.sec_8k).

list_filings_by_form and fetch_filing_text are mocked -- no network
access. What's under test is the orchestration: every listed accession
gets ingested (using the metadata already returned by the listing call,
not a redundant get_filing_metadata fetch), and the whole thing is
idempotent on rerun.
"""

from sqlalchemy import select

from app.ingestion.sec_8k import ingest_all_8ks
from app.models import Company, Filing

FAKE_8K_LISTING = [
    {"accession_number": "acc-1", "form": "8-K", "report_date": "2024-01-05", "filed_date": "2024-01-08", "primary_document": "doc1.htm"},
    {"accession_number": "acc-2", "form": "8-K", "report_date": "2024-02-10", "filed_date": "2024-02-12", "primary_document": "doc2.htm"},
]


def _mock_pipeline(monkeypatch, listing=FAKE_8K_LISTING):
    monkeypatch.setattr("app.ingestion.sec_8k.list_filings_by_form", lambda cik, form: listing)
    monkeypatch.setattr(
        "app.ingestion.sec_filings.fetch_filing_text",
        lambda cik, accession_number, primary_document: (
            "Item 5.02 Departure of a director. Some short filing text.",
            "https://example.com/doc.htm",
        ),
    )


def test_ingests_every_8k_returned_by_the_listing(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_pipeline(monkeypatch)

    ingest_all_8ks(1)

    filings = db_session.execute(select(Filing)).scalars().all()
    assert {f.accession_number for f in filings} == {"acc-1", "acc-2"}
    assert all(f.form == "8-K" for f in filings)


def test_is_idempotent_on_rerun(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_pipeline(monkeypatch)

    ingest_all_8ks(1)
    ingest_all_8ks(1)  # re-running against the same listing must not duplicate rows

    filings = db_session.execute(select(Filing)).scalars().all()
    assert len(filings) == 2


def test_empty_listing_ingests_nothing(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="TEST", name="Test Co"))
    db_session.commit()
    _mock_pipeline(monkeypatch, listing=[])

    ingest_all_8ks(1)

    assert db_session.execute(select(Filing)).scalars().all() == []
