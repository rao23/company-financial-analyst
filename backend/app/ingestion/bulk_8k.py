"""Bulk-ingest 8-K filings for every company in the DB (sec_8k.py was only
ever run for Apple -- this covers the rest).

Run with: python -m app.ingestion.bulk_8k

Resumable: skips any company that already has at least one 8-K Filing row.

Concurrent (MAX_WORKERS threads), safe this time: fetch_filing._get now
enforces a real shared rate limiter (a sliding 1-second window, 7
requests/sec, under SEC's stated 10/sec) at the actual network-call site,
not an approximation via per-company/per-filing sleeps -- that
approximation is what let an earlier version of this script trip SEC's
rate limiter (HTTP 429) within minutes of adding concurrency. With the
real bottleneck enforced centrally, more worker threads just overlap
network latency more efficiently; they can't push the aggregate request
rate past what the limiter allows no matter how many there are.

On a 429 (should be rare now, kept as defense-in-depth): cools down and
retries once before giving up on that company -- giving up just means
it's picked up again on the next (resumable) run, not lost.

Chunking happens inline (via ingest_all_8ks -> ingest_filing), but
embedding does not -- run app.rag.embed_chunks once this finishes, same
decoupled ingest-then-embed pattern as every other phase.
"""

import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

from app.db import SessionLocal
from app.ingestion.sec_8k import ingest_all_8ks
from app.models import Company, Filing

MAX_WORKERS = 6
RATE_LIMIT_COOLDOWN_SECONDS = 60

_progress_lock = threading.Lock()


def _companies_needing_8ks(db) -> list[Company]:
    already_covered = {
        cik for (cik,) in db.execute(select(Filing.company_cik).where(Filing.form == "8-K").distinct())
    }
    companies = db.execute(select(Company)).scalars().all()
    return [c for c in companies if c.cik not in already_covered]


def _process_company(company: Company, total: int, processed: list[int], failed: list[str]) -> None:
    success = False
    try:
        ingest_all_8ks(company.cik)
        success = True
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  Rate limited on {company.ticker} -- cooling down {RATE_LIMIT_COOLDOWN_SECONDS}s.")
            time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
            try:
                ingest_all_8ks(company.cik)
                success = True
            except Exception as retry_error:
                print(f"  {company.ticker} (CIK {company.cik}): failed again after cooldown ({retry_error})")
        else:
            print(f"  {company.ticker} (CIK {company.cik}): failed ({e})")
    except OSError as e:
        # Local socket/port exhaustion (e.g. Errno 49) is transient and
        # distinct from SEC rate-limiting -- same cooldown-and-retry-once
        # treatment gives the OS time to release exhausted ephemeral ports.
        print(f"  Local network error on {company.ticker} ({e}) -- cooling down {RATE_LIMIT_COOLDOWN_SECONDS}s.")
        time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
        try:
            ingest_all_8ks(company.cik)
            success = True
        except Exception as retry_error:
            print(f"  {company.ticker} (CIK {company.cik}): failed again after cooldown ({retry_error})")
    except Exception as e:
        print(f"  {company.ticker} (CIK {company.cik}): failed ({e})")

    with _progress_lock:
        if not success:
            failed.append(company.ticker)
        processed[0] += 1
        if processed[0] % 50 == 0:
            print(f"Progress: {processed[0]}/{total} companies processed. {len(failed)} failures so far.")


def bulk_ingest_8ks() -> None:
    db = SessionLocal()
    try:
        companies = _companies_needing_8ks(db)
    finally:
        db.close()

    total = len(companies)
    print(f"{total} companies still need 8-K ingestion. Using {MAX_WORKERS} concurrent workers.")

    processed = [0]
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_process_company, company, total, processed, failed) for company in companies]
        for future in as_completed(futures):
            future.result()

    print(f"Done. {total - len(failed)}/{total} companies succeeded.")
    if failed:
        print(f"Failed tickers: {failed}")


if __name__ == "__main__":
    bulk_ingest_8ks()
