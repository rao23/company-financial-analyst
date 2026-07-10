"""Bulk-backfill price history for every company in the DB (Phase 1's
price_history.py was only ever run for 2 verification tickers -- this
covers the rest).

Run with: python -m app.ingestion.bulk_price_history

Batches tickers through yf.download() rather than one Ticker().history()
call per company -- faster, and gentler on Yahoo's unofficial (and
unpublished) rate limits than 8,000 sequential single-ticker requests.

Resumable: skips any company that already has at least one price_history
row, so an interrupted run can just be restarted from where it left off.
"""

import time

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Company, PriceHistory

BATCH_SIZE = 50
PAUSE_BETWEEN_BATCHES_SECONDS = 2


def _companies_needing_price_history(db) -> list[Company]:
    already_covered = {cik for (cik,) in db.execute(select(PriceHistory.company_cik).distinct())}
    companies = db.execute(select(Company)).scalars().all()
    return [c for c in companies if c.cik not in already_covered]


def _insert_prices_for_ticker(db, company: Company, history: pd.DataFrame) -> int:
    if history.empty:
        return 0
    inserted = 0
    for row_date, row in history.iterrows():
        if pd.isna(row["Close"]) or pd.isna(row["Volume"]):
            continue  # batch downloads can leave NaN rows for tickers with gaps/holiday mismatches
        stmt = (
            pg_insert(PriceHistory)
            .values(company_cik=company.cik, date=row_date.date(), close=float(row["Close"]), volume=int(row["Volume"]))
            .on_conflict_do_nothing(constraint="uq_price_history_date")
        )
        db.execute(stmt)
        inserted += 1
    return inserted


def bulk_load_price_history() -> None:
    db = SessionLocal()
    try:
        companies = _companies_needing_price_history(db)
        print(f"{len(companies)} companies still need price history.")
        total_batches = -(-len(companies) // BATCH_SIZE)

        for batch_num, i in enumerate(range(0, len(companies), BATCH_SIZE), start=1):
            batch = companies[i : i + BATCH_SIZE]
            tickers = [c.ticker for c in batch]
            by_ticker = {c.ticker: c for c in batch}

            try:
                data = yf.download(tickers, period="max", group_by="ticker", threads=True, progress=False)
            except Exception as e:
                print(f"Batch {batch_num}/{total_batches} failed entirely: {e}")
                time.sleep(PAUSE_BETWEEN_BATCHES_SECONDS)
                continue

            batch_inserted = 0
            batch_failed = []
            for ticker in tickers:
                try:
                    history = data[ticker] if len(tickers) > 1 else data
                    batch_inserted += _insert_prices_for_ticker(db, by_ticker[ticker], history)
                except Exception:
                    batch_failed.append(ticker)
            db.commit()

            status = f"Batch {batch_num}/{total_batches}: {len(batch)} tickers, {batch_inserted} price rows inserted."
            if batch_failed:
                status += f" Failed: {batch_failed}"
            print(status)
            time.sleep(PAUSE_BETWEEN_BATCHES_SECONDS)
    finally:
        db.close()


if __name__ == "__main__":
    bulk_load_price_history()
