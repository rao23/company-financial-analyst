"""Tests for Item-heading chunking (app.rag.chunking).

The fixture text below deliberately reproduces the three cases the module
docstring calls out as easy to confuse: a table-of-contents listing (bare
heading + title + page number), a real section heading, and an in-text
cross-reference to an Item number that isn't a section boundary.
"""

from app.rag.chunking import chunk_filing, split_by_item_heading

_LONG_PADDING = "Cash and cash equivalents. " * 200  # pushes the section past LONG_SECTION_THRESHOLD

FILING_TEXT = f"""
Item 1.
Financial Statements
3
Item 2.
Management's Discussion and Analysis
15

PART I

Item 1.    Financial Statements

{_LONG_PADDING}

Item 2.    Management's Discussion and Analysis

See Item 1. of Part II for the required disclosure. Quarterly Highlights follow.
"""


def test_toc_entries_are_discarded_in_favor_of_the_real_heading():
    sections = split_by_item_heading(FILING_TEXT)
    labels = [label for label, _ in sections]
    assert labels.count("Item 1. Financial Statements") == 1
    assert labels.count("Item 2. Management's Discussion and Analysis") == 1


def test_sections_are_ordered_by_position_in_the_document():
    sections = split_by_item_heading(FILING_TEXT)
    labels = [label for label, _ in sections]
    assert labels == [
        "Item 1. Financial Statements",
        "Item 2. Management's Discussion and Analysis",
    ]


def test_in_text_cross_reference_does_not_create_a_spurious_section():
    # "Item 1." appears again mid-sentence inside the MD&A section, but
    # isn't followed by a known title ("Financial Statements" or "Legal
    # Proceedings") -- it must not be treated as a boundary.
    sections = split_by_item_heading(FILING_TEXT)
    assert len(sections) == 2


def test_falls_back_to_full_text_when_no_known_item_headings_found():
    text = "Just some plain filing text with no Item headings at all."
    assert split_by_item_heading(text) == [("Full Text", text)]


def test_long_section_is_sub_chunked_and_short_section_is_not():
    chunks = chunk_filing(FILING_TEXT)

    financial_statements_chunks = [c for c in chunks if c["section"] == "Item 1. Financial Statements"]
    assert len(financial_statements_chunks) > 1
    assert [c["chunk_index"] for c in financial_statements_chunks] == list(
        range(len(financial_statements_chunks))
    )

    mdna_chunks = [c for c in chunks if c["section"] == "Item 2. Management's Discussion and Analysis"]
    assert len(mdna_chunks) == 1
    assert mdna_chunks[0]["chunk_index"] == 0
