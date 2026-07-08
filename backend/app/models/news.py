import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.company import Company  # noqa: F401 — resolves the relationship() string ref
from app.models.filing import EMBEDDING_DIM  # same embedding model as filings, same dimension


class NewsArticle(Base):
    """One Finnhub news article for a company.

    `body` is Finnhub's `summary` field, not scraped full article text —
    the free `company-news` endpoint doesn't provide full bodies, and
    scraping arbitrary source URLs (paywalls, inconsistent HTML) is out of
    scope for v1. `finnhub_id` (not source_url) is the dedup key: it's a
    stable integer Finnhub assigns per article, safer than comparing
    possibly-truncated URL strings.
    """

    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("company_cik", "finnhub_id", name="uq_news_article_finnhub_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    finnhub_id: Mapped[int]
    published_at: Mapped[datetime.datetime]
    headline: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1000))

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
    """Tracks which (company, date-range) windows have already been pulled
    from Finnhub, so overlapping requests -- e.g. Phase 4's expanding-window
    retries (14 -> 90 -> 180 days) -- never re-fetch or re-embed the same
    articles. See DESIGN.md's news ingestion trigger note.

    v1 dedup check (finnhub_news.py) only matches a single logged row that
    fully covers the requested range -- it doesn't merge multiple
    overlapping logged windows. A known simplification, not a correctness
    issue: it can only cause a redundant re-fetch (wasted API call, not
    wrong data), never a missed one.
    """

    __tablename__ = "news_fetch_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    date_from: Mapped[datetime.date]
    date_to: Mapped[datetime.date]
    fetched_at: Mapped[datetime.datetime]
