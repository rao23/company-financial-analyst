"""Ingest Massive/Polygon news for a ticker + date range (DESIGN.md's news
data source) -- real historical depth, unlike Finnhub's free tier, which
only returns the last ~4 days regardless of requested range (see
finnhub_news.py and DESIGN.md §12).

Run with: python -m app.ingestion.massive_news AAPL 2021-01-01 2026-07-08

Follows next_url cursor pagination to get every article in range, not
just the first page -- Polygon's next_url doesn't carry the API key over
automatically, so it has to be re-appended on every page.
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Company, NewsArticle, NewsChunk, NewsFetchLog
from app.rag.news_chunking import chunk_news_body

MASSIVE_API_KEY = os.environ["MASSIVE_API_KEY"]
MASSIVE_NEWS_URL = "https://api.polygon.io/v2/reference/news"
PAGE_LIMIT = 1000


def fetch_company_news(ticker: str, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "ticker": ticker,
            "published_utc.gte": date_from.isoformat(),
            "published_utc.lte": date_to.isoformat(),
            "limit": PAGE_LIMIT,
            "apiKey": MASSIVE_API_KEY,
        }
    )
    url = f"{MASSIVE_NEWS_URL}?{params}"

    articles = []
    while url:
        with urllib.request.urlopen(url) as response:
            data = json.load(response)
        articles.extend(data.get("results", []))
        next_url = data.get("next_url")
        url = f"{next_url}&apiKey={MASSIVE_API_KEY}" if next_url else None
    return articles


def _window_already_fetched(db, company_cik: int, date_from: datetime.date, date_to: datetime.date) -> bool:
    covering = db.execute(
        select(NewsFetchLog).where(
            NewsFetchLog.company_cik == company_cik,
            NewsFetchLog.source_name == "massive",
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

        inserted_count = 0
        skipped_errors = 0

        for item in articles:
            if not item.get("description"):
                continue  # occasional entries with no real summary

            try:
                # A savepoint per article: real-world international news
                # data has surprises (e.g. one company's percent-encoded
                # non-ASCII URL blew past a column limit) -- without this,
                # one bad row aborts the whole transaction and silently
                # drops every other article fetched for this company.
                with db.begin_nested():
                    stmt = (
                        pg_insert(NewsArticle)
                        .values(
                            company_cik=company.cik,
                            source_name="massive",
                            external_id=item["id"],
                            published_at=datetime.datetime.fromisoformat(item["published_utc"]),
                            headline=item["title"][:500],
                            body=item["description"],
                            source_url=item["article_url"][:2000],
                        )
                        .on_conflict_do_nothing(constraint="uq_news_article_source_external_id")
                        .returning(NewsArticle.id)
                    )
                    article_id = db.execute(stmt).scalar_one_or_none()
                    if article_id is None:
                        continue  # already ingested this article for this company

                    for chunk in chunk_news_body(item["description"]):
                        db.add(
                            NewsChunk(
                                article_id=article_id,
                                chunk_index=chunk["chunk_index"],
                                chunk_text=chunk["chunk_text"],
                            )
                        )
                    db.flush()  # execute the chunk inserts now, inside this savepoint
                    inserted_count += 1
            except Exception as e:
                skipped_errors += 1
                print(f"  Skipped one article for {ticker} due to an insert error: {e}")

        db.add(
            NewsFetchLog(
                company_cik=company.cik,
                source_name="massive",
                date_from=date_from,
                date_to=date_to,
                fetched_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        db.commit()

        status = f"Fetched {len(articles)} articles for {ticker} [{date_from}..{date_to}], inserted {inserted_count} new rows."
        if skipped_errors:
            status += f" Skipped {skipped_errors} due to errors."
        print(status)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python -m app.ingestion.massive_news <TICKER> <FROM:YYYY-MM-DD> <TO:YYYY-MM-DD>")
        sys.exit(1)
    ingest_news(
        sys.argv[1].upper(),
        datetime.date.fromisoformat(sys.argv[2]),
        datetime.date.fromisoformat(sys.argv[3]),
    )
