"""Embed any filing_chunks/news_chunks rows missing an embedding, using a
local sentence-transformers model — no embedding API cost (DESIGN.md §7).

Run with: python -m app.rag.embed_chunks
Or scoped to specific tickers (e.g. to unblock testing against a handful
of companies without waiting on the full backlog): python -m
app.rag.embed_chunks AAPL TSLA NVDA -- fully incremental either way
(WHERE embedding IS NULL), so a scoped run now and a full run later never
redo work or conflict.

bge-small-en-v1.5 uses *asymmetric* encoding (confirmed from its model
card, not assumed): queries need the instruction prefix
"Represent this sentence for searching relevant passages:", but passages
being indexed — which is all this script ever embeds — need no prefix at
all. The retrieval query side is what needs the prefix (app.rag.retrieval);
getting this backwards wouldn't error, it would just silently retrieve
worse matches.
"""

import sys

from sentence_transformers import SentenceTransformer
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Company, Filing, FilingChunk, NewsArticle, NewsChunk

MODEL_NAME = "BAAI/bge-small-en-v1.5"
BATCH_SIZE = 32


def _embed_pending(model: SentenceTransformer, chunk_cls, label: str, company_ciks: list[int] | None = None) -> None:
    db = SessionLocal()
    try:
        stmt = select(chunk_cls).where(chunk_cls.embedding.is_(None))
        if company_ciks is not None:
            if chunk_cls is FilingChunk:
                stmt = stmt.join(Filing, FilingChunk.filing_id == Filing.id).where(Filing.company_cik.in_(company_ciks))
            else:
                stmt = stmt.join(NewsArticle, NewsChunk.article_id == NewsArticle.id).where(
                    NewsArticle.company_cik.in_(company_ciks)
                )

        chunks = db.execute(stmt).scalars().all()

        if not chunks:
            print(f"No {label} pending embedding.")
            return

        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            # No instruction prefix — these are passages, not queries.
            vectors = model.encode([c.chunk_text for c in batch])
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector.tolist()
            db.commit()
            print(f"Embedded {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)} {label}")
    finally:
        db.close()


def embed_pending_chunks(tickers: list[str] | None = None) -> None:
    company_ciks = None
    if tickers is not None:
        db = SessionLocal()
        try:
            company_ciks = list(
                db.execute(select(Company.cik).where(Company.ticker.in_([t.upper() for t in tickers]))).scalars()
            )
        finally:
            db.close()

    model = SentenceTransformer(MODEL_NAME)
    _embed_pending(model, FilingChunk, "chunks", company_ciks)
    _embed_pending(model, NewsChunk, "news chunks", company_ciks)


if __name__ == "__main__":
    embed_pending_chunks(sys.argv[1:] or None)
