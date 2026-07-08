"""Split filing text into Item-heading sections, then sub-chunk long
sections with overlap (DESIGN.md §7).

The Item-heading split (split_by_item_heading) is a TODO for you to
implement — this is the actual RAG chunking-strategy decision, not
boilerplate. Ran fetch_filing against Apple's real 10-Q first to see what
you're dealing with; three different things all match a naive "Item N"
search and you'll need to tell them apart:

  1. Table-of-contents entries: bare "Item 1." with no title following
     (several in a row near the top of the document).
  2. In-text cross-references: "...discussed in Part I, Item 1A of the
     2023 Form 10-K under the heading 'Risk Factors'" — mentions an Item
     mid-sentence, not a section boundary.
  3. Real section headings: "Item 2.\xa0\xa0\xa0\xa0Management's Discussion
     and Analysis..." — the number+period is immediately followed by
     whitespace padding and the actual section title.

Only #3 is a real chunk boundary. Test against a few different companies'
filings before trusting this broadly — formatting conventions vary some
across filers and years.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

# TODO(you): the threshold for "long enough to need sub-chunking" should
# eventually be driven by the embedding model's actual token budget (next
# task picks the model) — this character count is a placeholder estimate,
# not calibrated against a real tokenizer yet.
LONG_SECTION_THRESHOLD = 1500
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


def split_by_item_heading(raw_text: str) -> list[tuple[str, str]]:
    """Split filing text into (section_heading, section_text) pairs.

    TODO(you): implement this. Find real section-heading positions (see
    the module docstring for how to distinguish them from TOC entries and
    cross-references), then slice raw_text between consecutive headings.
    """
    raise NotImplementedError("TODO: split raw_text into Item-heading sections")


def sub_chunk_section(section_text: str) -> list[str]:
    """Sub-chunk a long section with overlap. Only called for sections
    exceeding LONG_SECTION_THRESHOLD — short sections stay as one chunk.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    return splitter.split_text(section_text)


def chunk_filing(raw_text: str) -> list[dict]:
    """Returns [{"section": ..., "chunk_index": ..., "chunk_text": ...}, ...]."""
    chunks = []
    for section_heading, section_text in split_by_item_heading(raw_text):
        if len(section_text) <= LONG_SECTION_THRESHOLD:
            chunks.append({"section": section_heading, "chunk_index": 0, "chunk_text": section_text})
        else:
            for i, sub_chunk in enumerate(sub_chunk_section(section_text)):
                chunks.append({"section": section_heading, "chunk_index": i, "chunk_text": sub_chunk})
    return chunks
