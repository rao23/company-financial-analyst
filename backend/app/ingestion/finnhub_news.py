"""Ingest Finnhub company news for a ticker + date range (DESIGN.md's
Finnhub news data source), chunked and ready for embedding.

Run with: python -m app.ingestion.finnhub_news AAPL 2024-01-01 2024-03-31

Window dedup: before calling Finnhub, checks news_fetch_log for a single
already-logged (company, date_from, date_to) row that fully covers the
requested range, and skips the API call entirely if so -- see
app.models.news.NewsFetchLog for why this only prevents redundant
re-fetches, not wrong data, even though it doesn't merge overlapping
windows.
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Company, NewsArticle, NewsChunk, NewsFetchLog
from app.rag.news_chunking import chunk_news_body

FINNHUB_API_KEY = os.environ["FINNHUB_API_KEY"]
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"


def fetch_company_news(ticker: str, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "symbol": ticker,
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "token": FINNHUB_API_KEY,
        }
    )
    with urllib.request.urlopen(f"{FINNHUB_NEWS_URL}?{params}") as response:
        return json.load(response)


def _window_already_fetched(db, company_cik: int, date_from: datetime.date, date_to: datetime.date) -> bool:
    covering = db.execute(
        select(NewsFetchLog).where(
            NewsFetchLog.company_cik == company_cik,
            NewsFetchLog.date_from <= date_from,
            NewsFetchLog.date_to >= date_to,
        )
    ).first()
    return covering is not None


def ingest_news(ticker: str, date_from: datetime.date, date_to: datetime.date) -> None:
    db = SessionLocal()
    try:
        company = db.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if company is None:
            print(f"No company found for ticker {ticker!r} — run sec_companies ingestion first.")
            return

        if _window_already_fetched(db, company.cik, date_from, date_to):
            print(f"{ticker} [{date_from}..{date_to}] already covered by a prior fetch — skipping.")
            return

        articles = fetch_company_news(ticker, date_from, date_to)

        before = db.execute(select(func.count()).select_from(NewsArticle)).scalar_one()

        for item in articles:
            if not item.get("summary"):
                continue  # Finnhub occasionally returns placeholder/empty entries

            stmt = (
                pg_insert(NewsArticle)
                .values(
                    company_cik=company.cik,
                    finnhub_id=item["id"],
                    published_at=datetime.datetime.fromtimestamp(item["datetime"], tz=datetime.UTC),
                    headline=item["headline"],
                    body=item["summary"],
                    source_url=item["url"],
                )
                .on_conflict_do_nothing(constraint="uq_news_article_finnhub_id")
                .returning(NewsArticle.id)
            )
            article_id = db.execute(stmt).scalar_one_or_none()
            if article_id is None:
                continue  # already ingested this article for this company

            for chunk in chunk_news_body(item["summary"]):
                db.add(
                    NewsChunk(
                        article_id=article_id,
                        chunk_index=chunk["chunk_index"],
                        chunk_text=chunk["chunk_text"],
                    )
                )

        db.add(
            NewsFetchLog(
                company_cik=company.cik,
                date_from=date_from,
                date_to=date_to,
                fetched_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        db.commit()

        after = db.execute(select(func.count()).select_from(NewsArticle)).scalar_one()
        print(
            f"Fetched {len(articles)} articles for {ticker} [{date_from}..{date_to}], "
            f"inserted {after - before} new rows."
        )
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python -m app.ingestion.finnhub_news <TICKER> <FROM:YYYY-MM-DD> <TO:YYYY-MM-DD>")
        sys.exit(1)
    ingest_news(
        sys.argv[1].upper(),
        datetime.date.fromisoformat(sys.argv[2]),
        datetime.date.fromisoformat(sys.argv[3]),
    )
