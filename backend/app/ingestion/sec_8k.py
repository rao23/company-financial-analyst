"""Ingest all 8-K filings for a company (DESIGN.md's 8-K material-event
data source: EDGAR submissions API, filtered to form type 8-K).

Run with: python -m app.ingestion.sec_8k 320193

Reuses the exact same fetch -> chunk -> write pipeline as sec_filings.py.
No separate 8-K chunking logic is needed: chunk_filing() only splits on
KNOWN_10Q_ITEMS headings, and an 8-K's own Item numbering ("Item 5.02",
"Item 9.01", etc.) doesn't collide with those titles, so it correctly
falls through to the "Full Text" + sub-chunking path already in
chunking.py. That's also the right outcome, not just a coincidence: an
8-K is usually 1-3 pages describing a single event already, so there's
little to gain from splitting it into sub-sections the way a 10-Q needs.
"""

import sys

from app.ingestion.sec_filings import ingest_filing
from app.rag.fetch_filing import list_filings_by_form


def ingest_all_8ks(cik: int) -> None:
    filings = list_filings_by_form(cik, form="8-K")

    ingested = 0
    for filing in filings:
        if ingest_filing(cik, filing["accession_number"]):
            ingested += 1

    print(f"Processed {len(filings)} 8-K filings for CIK {cik}, ingested {ingested} new.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.ingestion.sec_8k <CIK>")
        sys.exit(1)
    ingest_all_8ks(int(sys.argv[1]))
