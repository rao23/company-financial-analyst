"""Tests for company + date-range filtered retrieval (app.rag.retrieval).

embed_query is mocked out everywhere here -- these tests are about the SQL
filtering/ranking logic in search_filing_chunks, not embedding quality, so
loading the real sentence-transformers model would only slow the suite
down for no signal. Fixed-direction vectors stand in for real embeddings:
cosine distance between them is still meaningful for ranking assertions.
"""

import datetime
import itertools

import pytest

from app.models import Company, Filing, FilingChunk
from app.models.filing import EMBEDDING_DIM
from app.rag.retrieval import search_filing_chunks

DATE_FROM = datetime.date(2023, 1, 1)
DATE_TO = datetime.date(2024, 12, 31)


def _vector(direction: float) -> list[float]:
    return [direction] * EMBEDDING_DIM


_UNSET = object()  # embedding=None is meaningful (an un-embedded chunk), so it can't double as "use the default"
_accession_counter = itertools.count(1)  # accession_number is VARCHAR(20) -- keep fixture values short


@pytest.fixture(autouse=True)
def _mock_embed_query(monkeypatch):
    monkeypatch.setattr("app.rag.retrieval.embed_query", lambda query: _vector(1.0))


def _seed_chunk(db_session, cik, filed_date, chunk_text="chunk", embedding=_UNSET):
    if embedding is _UNSET:
        embedding = _vector(1.0)
    db_session.merge(Company(cik=cik, ticker=f"T{cik}", name=f"Company {cik}"))
    filing = Filing(
        company_cik=cik,
        accession_number=f"acc-{next(_accession_counter)}",
        form="10-Q",
        period=filed_date,
        filed_date=filed_date,
        source_url="https://example.com",
        raw_text="irrelevant",
    )
    db_session.add(filing)
    db_session.flush()  # assigns filing.id
    chunk = FilingChunk(
        filing_id=filing.id,
        section="Item 1. Financial Statements",
        chunk_index=0,
        chunk_text=chunk_text,
        embedding=embedding,
    )
    db_session.add(chunk)
    db_session.commit()
    return chunk


def test_excludes_chunks_outside_the_date_range(db_session):
    _seed_chunk(db_session, cik=1, filed_date=datetime.date(2024, 3, 1), chunk_text="in range")
    _seed_chunk(db_session, cik=1, filed_date=datetime.date(2020, 3, 1), chunk_text="out of range")

    results = search_filing_chunks(db_session, company_cik=1, query="q", date_from=DATE_FROM, date_to=DATE_TO)

    assert [r.chunk_text for r in results] == ["in range"]


def test_never_returns_another_companys_chunks(db_session):
    _seed_chunk(db_session, cik=1, filed_date=datetime.date(2024, 3, 1), chunk_text="company 1")
    _seed_chunk(db_session, cik=2, filed_date=datetime.date(2024, 3, 1), chunk_text="company 2")

    results = search_filing_chunks(db_session, company_cik=1, query="q", date_from=DATE_FROM, date_to=DATE_TO)

    assert [r.chunk_text for r in results] == ["company 1"]


def test_excludes_chunks_without_an_embedding_yet(db_session):
    _seed_chunk(db_session, cik=1, filed_date=datetime.date(2024, 3, 1), embedding=None)

    results = search_filing_chunks(db_session, company_cik=1, query="q", date_from=DATE_FROM, date_to=DATE_TO)

    assert results == []


def test_ranks_by_similarity_to_the_query_vector(db_session):
    _seed_chunk(db_session, cik=1, filed_date=datetime.date(2024, 1, 1), chunk_text="opposite", embedding=_vector(-1.0))
    _seed_chunk(db_session, cik=1, filed_date=datetime.date(2024, 2, 1), chunk_text="matching", embedding=_vector(1.0))

    results = search_filing_chunks(db_session, company_cik=1, query="q", date_from=DATE_FROM, date_to=DATE_TO)

    assert results[0].chunk_text == "matching"


def test_respects_top_k(db_session):
    for day in range(1, 6):
        _seed_chunk(db_session, cik=1, filed_date=datetime.date(2024, 1, day), chunk_text=f"chunk-{day}")

    results = search_filing_chunks(db_session, company_cik=1, query="q", date_from=DATE_FROM, date_to=DATE_TO, top_k=2)

    assert len(results) == 2
