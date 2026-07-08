"""Embed any filing_chunks/news_chunks rows missing an embedding, using a
local sentence-transformers model — no embedding API cost (DESIGN.md §7).

Run with: python -m app.rag.embed_chunks

bge-small-en-v1.5 uses *asymmetric* encoding (confirmed from its model
card, not assumed): queries need the instruction prefix
"Represent this sentence for searching relevant passages:", but passages
being indexed — which is all this script ever embeds — need no prefix at
all. The retrieval query side is what needs the prefix (app.rag.retrieval);
getting this backwards wouldn't error, it would just silently retrieve
worse matches.
"""

from sentence_transformers import SentenceTransformer
from sqlalchemy import select

from app.db import SessionLocal
from app.models import FilingChunk, NewsChunk

MODEL_NAME = "BAAI/bge-small-en-v1.5"
BATCH_SIZE = 32


def _embed_pending(model: SentenceTransformer, chunk_cls, label: str) -> None:
    db = SessionLocal()
    try:
        chunks = db.execute(
            select(chunk_cls).where(chunk_cls.embedding.is_(None))
        ).scalars().all()

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


def embed_pending_chunks() -> None:
    model = SentenceTransformer(MODEL_NAME)
    _embed_pending(model, FilingChunk, "chunks")
    _embed_pending(model, NewsChunk, "news chunks")


if __name__ == "__main__":
    embed_pending_chunks()
