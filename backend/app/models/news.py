import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.company import Company  # noqa: F401 — resolves the relationship() string ref
from app.models.filing import EMBEDDING_DIM  # same embedding model as filings, same dimension


class NewsArticle(Base):
    """One news article for a company, from any configured provider
    (Finnhub, Massive/Polygon, ...).

    `source_name` + `external_id` together are the dedup key -- external_id
    alone isn't safe across providers (Finnhub uses small integers, Massive
    uses long hash strings; a collision is astronomically unlikely but not
    worth risking when the fix is one extra column). `external_id` is a
    string even for Finnhub's integer IDs, so both providers share one
    column type.

    `body` is a summary/description from the provider, not scraped full
    article text -- neither Finnhub's free tier nor Massive's News API give
    full article bodies, and scraping arbitrary source URLs (paywalls,
    inconsistent HTML) is out of scope for v1.
    """

    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("company_cik", "source_name", "external_id", name="uq_news_article_source_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    source_name: Mapped[str] = mapped_column(String(20))  # "finnhub" | "massive"
    external_id: Mapped[str] = mapped_column(String(100))
    published_at: Mapped[datetime.datetime]
    headline: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    # 2000, not 1000: some international outlets' URLs are heavily
    # percent-encoded (non-ASCII characters in the path) and blew past
    # 1000 in real data, aborting that entire company's insert batch.
    source_url: Mapped[str] = mapped_column(String(2000))

    company: Mapped["Company"] = relationship()
    chunks: Mapped[list["NewsChunk"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class NewsChunk(Base):
    """One retrievable chunk of a news article's body.

    Mirrors filing_chunks' shape (chunk_text + embedding + source_type/
    trust_level) so both tables can be queried and weighted uniformly by
    the agent (DESIGN.md §5/§8) — `source_type`/`trust_level` are fixed
    per row since news is always unofficial, same reasoning as filings.
    """

    __tablename__ = "news_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"))
    chunk_index: Mapped[int]
    chunk_text: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="news")
    trust_level: Mapped[str] = mapped_column(String(20), default="unofficial")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    article: Mapped["NewsArticle"] = relationship(back_populates="chunks")


class NewsFetchLog(Base):
    """Tracks which (company, source, date-range) windows have already been
    pulled, so overlapping requests -- e.g. Phase 4's expanding-window
    retries (14 -> 90 -> 180 days) -- never re-fetch or re-embed the same
    articles. Scoped per source_name since Finnhub and Massive cover
    different real depth and are fetched independently -- a window logged
    for one provider must not cause the other's fetch to be skipped.

    v1 dedup check only matches a single logged row that fully covers the
    requested range -- it doesn't merge multiple overlapping logged
    windows. A known simplification, not a correctness issue: it can only
    cause a redundant re-fetch (wasted API call, not wrong data), never a
    missed one.
    """

    __tablename__ = "news_fetch_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    source_name: Mapped[str] = mapped_column(String(20))
    date_from: Mapped[datetime.date]
    date_to: Mapped[datetime.date]
    fetched_at: Mapped[datetime.datetime]
