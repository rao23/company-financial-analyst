"""Paragraph-based chunking for news article bodies (DESIGN.md §7).

Unlike filings, news bodies have no heading structure to exploit -- the
split is just paragraph breaks. Finnhub's `summary` field (what we store
as `body`, see app.models.news.NewsArticle) is usually short enough to
stay a single chunk, but sub_chunk_section is reused from chunking.py so
an unusually long paragraph still gets split with the same overlap logic
filings use, instead of producing one oversized, poorly-embeddable chunk.
"""

from app.rag.chunking import LONG_SECTION_THRESHOLD, sub_chunk_section


def chunk_news_body(body: str) -> list[dict]:
    """Returns [{"chunk_index": ..., "chunk_text": ...}, ...]."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [body.strip()]

    pieces = []
    for paragraph in paragraphs:
        if len(paragraph) <= LONG_SECTION_THRESHOLD:
            pieces.append(paragraph)
        else:
            pieces.extend(sub_chunk_section(paragraph))

    return [{"chunk_index": i, "chunk_text": text} for i, text in enumerate(pieces)]
