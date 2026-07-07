"""Load daily price history for one company via yfinance.

Run with: python -m app.ingestion.price_history AAPL

`period="max"` pulls yfinance's full available history in one call (since
IPO, or since Yahoo's own coverage begins) — no manual date chunking needed.
"""

import sys

import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Company, PriceHistory


def load_price_history(ticker: str) -> None:
    db = SessionLocal()
    try:
        company = db.execute(
            select(Company).where(Company.ticker == ticker)
        ).scalar_one_or_none()
        if company is None:
            print(f"No company found for ticker {ticker!r} — run sec_companies ingestion first.")
            return

        history = yf.Ticker(ticker).history(period="max")
        if history.empty:
            print(f"yfinance returned no data for {ticker!r}.")
            return

        count_stmt = (
            select(func.count())
            .select_from(PriceHistory)
            .where(PriceHistory.company_cik == company.cik)
        )
        before = db.execute(count_stmt).scalar_one()

        for row_date, row in history.iterrows():
            stmt = (
                pg_insert(PriceHistory)
                .values(
                    company_cik=company.cik,
                    date=row_date.date(),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
                .on_conflict_do_nothing(constraint="uq_price_history_date")
            )
            db.execute(stmt)
        db.commit()

        after = db.execute(count_stmt).scalar_one()
        print(
            f"Fetched {len(history)} price bars for {ticker} ({company.name}), "
            f"inserted {after - before} new rows."
        )
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.ingestion.price_history <TICKER>")
        sys.exit(1)
    load_price_history(sys.argv[1].upper())
