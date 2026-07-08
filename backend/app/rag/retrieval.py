"""Metadata-filtered, embedding-based retrieval over filing_chunks
(DESIGN.md §7): always filter by company + date range first, then rank
the filtered set by vector similarity — never a global vector search
across the whole corpus.

search_filing_chunks is a TODO for you to implement. Hints:
  - Query embedding is done for you (embed_query below) — it applies
    bge's query instruction prefix, which passages (what embed_chunks.py
    stores) deliberately don't get. Getting this backwards won't error,
    it'll just silently degrade retrieval quality.
  - pgvector's SQLAlchemy integration exposes distance operators directly
    on a Vector column, e.g. FilingChunk.embedding.cosine_distance(...) —
    smaller distance = more similar. Confirm this is actually the cosine
    operator, not L2, before trusting it (see TASKS.md Phase 2).
  - Filter FIRST — company_cik, and Filing.filed_date within the given
    range via a join to Filing — THEN order by similarity. The filter is
    what keeps this from ever becoming a global vector search; do it in
    the WHERE clause, not as a post-filter on already-ranked results.
"""

import datetime

from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Filing, FilingChunk

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_query(query: str) -> list[float]:
    """Embed a search query for retrieval — WITH the instruction prefix,
    unlike passages (see module docstring)."""
    vector = _get_model().encode(QUERY_INSTRUCTION + query)
    return vector.tolist()


def search_filing_chunks(
    db: Session,
    company_cik: int,
    query: str,
    date_from: datetime.date,
    date_to: datetime.date,
    top_k: int = 5,
) -> list[FilingChunk]:
    """Company + date-range filtered, then ranked by cosine similarity.

    Filters on Filing.filed_date (not Filing.period) deliberately: retrieval
    should only surface filings that existed as of the investigation date,
    not filings that describe that date's quarter but were filed later.
    """
    query_vector = embed_query(query)

    stmt = (
        select(FilingChunk)
        .join(Filing, FilingChunk.filing_id == Filing.id)
        .where(
            Filing.company_cik == company_cik,
            Filing.filed_date >= date_from,
            Filing.filed_date <= date_to,
            FilingChunk.embedding.is_not(None),
        )
        .order_by(FilingChunk.embedding.cosine_distance(query_vector))
        .limit(top_k)
    )
    return list(db.execute(stmt).scalars().all())
