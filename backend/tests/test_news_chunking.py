"""Tests for news paragraph chunking (app.rag.news_chunking)."""

from app.rag.news_chunking import chunk_news_body


def test_splits_on_paragraph_breaks():
    body = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_news_body(body)
    assert [c["chunk_text"] for c in chunks] == ["First paragraph.", "Second paragraph.", "Third paragraph."]
    assert [c["chunk_index"] for c in chunks] == [0, 1, 2]


def test_single_paragraph_stays_as_one_chunk():
    body = "Just one short paragraph, no breaks at all."
    chunks = chunk_news_body(body)
    assert len(chunks) == 1
    assert chunks[0]["chunk_text"] == body


def test_blank_paragraphs_are_dropped():
    body = "First.\n\n\n\nSecond."
    chunks = chunk_news_body(body)
    assert [c["chunk_text"] for c in chunks] == ["First.", "Second."]


def test_long_paragraph_is_sub_chunked():
    long_paragraph = "Word. " * 400  # well past LONG_SECTION_THRESHOLD, no internal paragraph breaks
    chunks = chunk_news_body(long_paragraph)
    assert len(chunks) > 1
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_empty_body_returns_a_single_empty_chunk():
    chunks = chunk_news_body("")
    assert chunks == [{"chunk_index": 0, "chunk_text": ""}]
