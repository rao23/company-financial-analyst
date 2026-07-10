"""Bulk-ingest Massive/Polygon news for every company in the DB, covering
the last YEARS_OF_HISTORY years.

Run with: python -m app.ingestion.bulk_massive_news

Resumable: skips any company already covered by a logged massive fetch
for the target window (NewsFetchLog, source_name="massive").

Concurrent (MAX_WORKERS threads): Massive's paid tier returned no
rate-limit headers on any test response, unlike SEC's strict, empirically
enforced 10 req/sec -- this doesn't need fetch_filing.py's shared rate
limiter. Still uses a modest worker count and per-company error isolation
as a reasonable-citizen default, not because a documented ceiling forced
this number.
"""

import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

from app.db import SessionLocal
from app.ingestion.massive_news import ingest_news
from app.models import Company, NewsFetchLog

MAX_WORKERS = 10
YEARS_OF_HISTORY = 5

_progress_lock = threading.Lock()


def _companies_needing_news(db, date_from: datetime.date, date_to: datetime.date) -> list[Company]:
    already_covered_ciks = {
        row.company_cik
        for row in db.execute(
            select(NewsFetchLog).where(
                NewsFetchLog.source_name == "massive",
                NewsFetchLog.date_from <= date_from,
                NewsFetchLog.date_to >= date_to,
            )
        ).scalars()
    }
    companies = db.execute(select(Company)).scalars().all()
    return [c for c in companies if c.cik not in already_covered_ciks]


def _process_company(
    company: Company, date_from: datetime.date, date_to: datetime.date, total: int, processed: list[int], failed: list[str]
) -> None:
    success = False
    try:
        ingest_news(company.ticker, date_from, date_to)
        success = True
    except Exception as e:
        print(f"  {company.ticker} (CIK {company.cik}): failed ({e})")

    with _progress_lock:
        if not success:
            failed.append(company.ticker)
        processed[0] += 1
        if processed[0] % 50 == 0:
            print(f"Progress: {processed[0]}/{total} companies processed. {len(failed)} failures so far.")


def bulk_ingest_news() -> None:
    date_to = datetime.date.today()
    date_from = date_to.replace(year=date_to.year - YEARS_OF_HISTORY)

    db = SessionLocal()
    try:
        companies = _companies_needing_news(db, date_from, date_to)
    finally:
        db.close()

    total = len(companies)
    print(f"{total} companies still need news [{date_from}..{date_to}]. Using {MAX_WORKERS} concurrent workers.")

    processed = [0]
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(_process_company, company, date_from, date_to, total, processed, failed)
            for company in companies
        ]
        for future in as_completed(futures):
            future.result()

    print(f"Done. {total - len(failed)}/{total} companies succeeded.")
    if failed:
        print(f"Failed tickers: {failed}")


if __name__ == "__main__":
    bulk_ingest_news()
