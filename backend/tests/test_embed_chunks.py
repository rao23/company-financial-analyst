"""Tests for the embedding pipeline (app.rag.embed_chunks).

SentenceTransformer is replaced with a fake that never loads a real model
-- these tests are about which rows get embedded and which don't, not
embedding quality.
"""

import datetime

from sqlalchemy import select

from app.models import Company, Filing, FilingChunk
from app.models.filing import EMBEDDING_DIM
from app.rag import embed_chunks
from app.rag.embed_chunks import embed_pending_chunks


class _FakeVector(list):
    def tolist(self):
        return list(self)


class _FakeSentenceTransformer:
    def __init__(self, model_name: str):
        pass

    def encode(self, texts):
        return [_FakeVector([0.0] * EMBEDDING_DIM) for _ in texts]


def _make_filing(db_session, cik=1) -> Filing:
    db_session.merge(Company(cik=cik, ticker=f"T{cik}", name=f"Company {cik}"))
    filing = Filing(
        company_cik=cik,
        accession_number=f"acc-{cik}",
        form="10-Q",
        period=datetime.date(2024, 1, 1),
        filed_date=datetime.date(2024, 2, 1),
        source_url="https://example.com",
        raw_text="irrelevant",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def test_embeds_chunks_missing_a_vector(db_session, monkeypatch):
    monkeypatch.setattr(embed_chunks, "SentenceTransformer", _FakeSentenceTransformer)
    filing = _make_filing(db_session)
    chunk = FilingChunk(filing_id=filing.id, section="Item 1", chunk_index=0, chunk_text="hello", embedding=None)
    db_session.add(chunk)
    db_session.commit()

    embed_pending_chunks()

    db_session.refresh(chunk)
    assert chunk.embedding is not None
    assert len(chunk.embedding) == EMBEDDING_DIM


def test_does_not_touch_chunks_that_already_have_an_embedding(db_session, monkeypatch):
    monkeypatch.setattr(embed_chunks, "SentenceTransformer", _FakeSentenceTransformer)
    filing = _make_filing(db_session)
    existing_vector = [0.5] * EMBEDDING_DIM
    chunk = FilingChunk(
        filing_id=filing.id, section="Item 1", chunk_index=0, chunk_text="already embedded", embedding=existing_vector
    )
    db_session.add(chunk)
    db_session.commit()

    embed_pending_chunks()

    db_session.refresh(chunk)
    assert chunk.embedding == existing_vector  # untouched -- the query filters embedding IS NULL


def test_no_pending_chunks_does_not_error(db_session, monkeypatch, capsys):
    monkeypatch.setattr(embed_chunks, "SentenceTransformer", _FakeSentenceTransformer)

    embed_pending_chunks()

    assert "No chunks pending embedding." in capsys.readouterr().out


def test_handles_more_chunks_than_one_batch(db_session, monkeypatch):
    monkeypatch.setattr(embed_chunks, "SentenceTransformer", _FakeSentenceTransformer)
    monkeypatch.setattr(embed_chunks, "BATCH_SIZE", 2)  # force multiple batches over a small fixture
    filing = _make_filing(db_session)
    chunks = [
        FilingChunk(filing_id=filing.id, section="Item 1", chunk_index=i, chunk_text=f"chunk {i}", embedding=None)
        for i in range(5)
    ]
    db_session.add_all(chunks)
    db_session.commit()

    embed_pending_chunks()

    remaining_unembedded = db_session.execute(
        select(FilingChunk).where(FilingChunk.embedding.is_(None))
    ).scalars().all()
    assert remaining_unembedded == []
