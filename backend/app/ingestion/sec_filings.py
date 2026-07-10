"""Fetch one filing, chunk it, and write Filing + FilingChunk rows.

Run with: python -m app.ingestion.sec_filings 320193 0000320193-24-000006

This is the glue between the fetcher (fetch_filing.py) and the chunker
(chunking.py) — neither writes to the database on its own. Embeddings
are populated separately by app.rag.embed_chunks, not here.
"""

import datetime
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Filing, FilingChunk
from app.rag.chunking import chunk_filing
from app.rag.fetch_filing import fetch_filing_text, get_filing_metadata


def ingest_filing(cik: int, accession_number: str, metadata: dict | None = None) -> bool:
    """Returns True if a new Filing was ingested, False if it already existed.

    `metadata`, if the caller already has it (e.g. list_filings_by_form's
    bulk listing), skips a redundant submissions.json re-fetch --
    get_filing_metadata does its own full fetch per call, which is wasteful
    when ingesting many filings for the same company back to back (this is
    what caused bulk_8k.py to trip SEC's rate limiter: a company with 100
    filings was making ~200 requests instead of ~101).
    """
    db = SessionLocal()
    try:
        existing = db.execute(
            select(Filing).where(Filing.accession_number == accession_number)
        ).scalar_one_or_none()
        if existing is not None:
            print(f"Filing {accession_number} already ingested (filing_id={existing.id}); skipping.")
            return False

        if metadata is None:
            metadata = get_filing_metadata(cik, accession_number)
        raw_text, source_url = fetch_filing_text(cik, accession_number, metadata["primary_document"])

        filing = Filing(
            company_cik=cik,
            accession_number=accession_number,
            form=metadata["form"],
            period=datetime.date.fromisoformat(metadata["report_date"]),
            filed_date=datetime.date.fromisoformat(metadata["filed_date"]),
            source_url=source_url,
            raw_text=raw_text,
        )
        db.add(filing)
        db.flush()  # assigns filing.id without committing yet

        chunks = chunk_filing(raw_text)
        for chunk in chunks:
            db.add(
                FilingChunk(
                    filing_id=filing.id,
                    section=chunk["section"],
                    chunk_index=chunk["chunk_index"],
                    chunk_text=chunk["chunk_text"],
                )
            )
        db.commit()
        print(f"Ingested {accession_number}: filing_id={filing.id}, {len(chunks)} chunks.")
        return True
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m app.ingestion.sec_filings <CIK> <ACCESSION_NUMBER>")
        sys.exit(1)
    ingest_filing(int(sys.argv[1]), sys.argv[2])
