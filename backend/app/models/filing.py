import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.company import Company  # noqa: F401 — resolves the relationship() string ref


class Filing(Base):
    """One SEC filing's metadata + full raw text."""

    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_filing_accession"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    accession_number: Mapped[str] = mapped_column(String(20))
    form: Mapped[str] = mapped_column(String(10))  # 10-K, 10-Q, 8-K
    period: Mapped[datetime.date]
    filed_date: Mapped[datetime.date]
    source_url: Mapped[str] = mapped_column(String(500))
    raw_text: Mapped[str] = mapped_column(Text)

    company: Mapped["Company"] = relationship()
    chunks: Mapped[list["FilingChunk"]] = relationship(
        back_populates="filing", cascade="all, delete-orphan"
    )


class FilingChunk(Base):
    """One retrievable chunk of a filing — the unit RAG retrieval returns.

    `embedding` isn't added yet; that's the next task (local embedding
    pipeline + pgvector column). `source_type`/`trust_level` are fixed for
    every row here since filings are always official — the columns exist
    so filing_chunks and news_chunks can be queried/weighted uniformly.
    """

    __tablename__ = "filing_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    section: Mapped[str] = mapped_column(String(200))  # e.g. "Item 1A. Risk Factors"
    chunk_index: Mapped[int]  # order within the section, for sub-chunked sections
    chunk_text: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="filing")
    trust_level: Mapped[str] = mapped_column(String(20), default="official")

    filing: Mapped["Filing"] = relationship(back_populates="chunks")
