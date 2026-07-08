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

import re
import unicodedata

from langchain_text_splitters import RecursiveCharacterTextSplitter

# TODO(you): the threshold for "long enough to need sub-chunking" should
# eventually be driven by the embedding model's actual token budget (next
# task picks the model) — this character count is a placeholder estimate,
# not calibrated against a real tokenizer yet.
LONG_SECTION_THRESHOLD = 1500
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200

# Standard 10-Q Item numbers/titles (Regulation S-K). A list of (number,
# title) pairs, not a dict keyed by number — numbers repeat across Part I
# (financial-statement items) and Part II (other information) with
# different titles, e.g. Item 1 is "Financial Statements" in Part I but
# "Legal Proceedings" in Part II.
#
# TODO(you): 10-Ks use an entirely different Item set (Item 1 Business,
# Item 7 MD&A, Item 8 Financial Statements, etc.) — this list only covers
# 10-Qs. Add a KNOWN_10K_ITEMS list before chunking 10-Ks.
KNOWN_10Q_ITEMS: list[tuple[str, str]] = [
    ("1", "Financial Statements"),
    ("2", "Management's Discussion and Analysis"),
    ("3", "Quantitative and Qualitative Disclosures About Market Risk"),
    ("4", "Controls and Procedures"),
    ("1", "Legal Proceedings"),
    ("1A", "Risk Factors"),
    ("2", "Unregistered Sales of Equity Securities"),
    ("3", "Defaults Upon Senior Securities"),
    ("4", "Mine Safety Disclosures"),
    ("5", "Other Information"),
    ("6", "Exhibits"),
]

_ITEM_CANDIDATE = re.compile(r"Item\s+(\d+[A-Za-z]?)\.\s*", re.IGNORECASE)
_PEEK_WINDOW = 80


def _normalize(text: str) -> str:
    """Collapse whitespace (including \xa0 non-breaking spaces from HTML)
    and normalize curly quotes to straight ones, so a hardcoded title like
    "Management's" matches the real extracted text's "Management's"."""
    text = text.replace("’", "'").replace("‘", "'")
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_by_item_heading(raw_text: str) -> list[tuple[str, str]]:
    """Split filing text into (section_heading, section_text) pairs.

    Finds every "Item N." occurrence, then only treats it as a real
    section boundary if the text immediately following it starts with a
    known title for that item number. This is what rejects table-of-
    contents entries (nothing meaningful follows) and in-text
    cross-references (followed by unrelated prose, not the section's
    actual title) — see the module docstring for real examples of each.
    """
    # label -> start_position. A table-of-contents entry lists the title
    # right after the item number too (e.g. "Item 1.\nFinancial
    # Statements\n1\n" — number, title, page number), which passes the
    # same "title immediately follows" check as a real heading. Since
    # SEC filings always place the TOC before the actual content, plain
    # dict assignment while iterating in document order keeps only the
    # *last* (real) occurrence of each label — the TOC entries get
    # silently overwritten.
    last_position_by_label: dict[str, int] = {}

    for match in _ITEM_CANDIDATE.finditer(raw_text):
        number = match.group(1)
        peek = _normalize(raw_text[match.end() : match.end() + _PEEK_WINDOW])

        for known_number, known_title in KNOWN_10Q_ITEMS:
            if number.upper() != known_number.upper():
                continue
            if peek.lower().startswith(known_title.lower()):
                last_position_by_label[f"Item {number}. {known_title}"] = match.start()
                break

    if not last_position_by_label:
        return [("Full Text", raw_text)]

    confirmed = sorted(last_position_by_label.items(), key=lambda pair: pair[1])

    sections = []
    for i, (label, start) in enumerate(confirmed):
        end = confirmed[i + 1][1] if i + 1 < len(confirmed) else len(raw_text)
        sections.append((label, raw_text[start:end].strip()))

    return sections


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
