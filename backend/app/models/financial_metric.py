import datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.company import Company  # noqa: F401 — resolves the relationship() string ref


class FinancialMetric(Base):
    """One (company, period) row of as-filed fundamentals — never restated.

    `period` is the filing's own primary reporting period (sub.txt "period",
    not a prior-year comparative bundled into a later filing). Every value
    here is selected via that rule plus the consolidated/segments-excluded
    filter — see ADR-0005. Written insert-if-absent only; never upsert-to-
    latest, so a later filing can never silently overwrite what was
    actually known as of `filed_date`.

    `ebitda`/`fcf` are intentionally nullable — they're derived from the
    raw components below by a separate derivation step (§6), not ingested
    directly (XBRL has no EBITDA/FCF tag).
    """

    __tablename__ = "financial_metrics"
    __table_args__ = (
        UniqueConstraint("company_cik", "period", name="uq_financial_metric_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    period: Mapped[datetime.date]
    fiscal_year: Mapped[int | None]
    fiscal_period: Mapped[str | None] = mapped_column(String(2))  # Q1/Q2/Q3/FY
    form: Mapped[str] = mapped_column(String(10))  # 10-K or 10-Q

    revenue: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)

    # Raw components for the derivation layer (§6) — not final metrics.
    operating_income: Mapped[float | None] = mapped_column(Float)
    depreciation_amortization: Mapped[float | None] = mapped_column(Float)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)
    capital_expenditures: Mapped[float | None] = mapped_column(Float)

    # Filled in later by the derivation layer, not by ingestion.
    ebitda: Mapped[float | None] = mapped_column(Float)
    fcf: Mapped[float | None] = mapped_column(Float)

    source_accession_number: Mapped[str] = mapped_column(String(20))
    filed_date: Mapped[datetime.date]
    was_restated: Mapped[bool] = mapped_column(Boolean, default=False)
    # Accession number of the restating filing. A plain string, not a FK to
    # a `filings` table — that table doesn't exist yet (it's a Phase 2
    # concern for filing_chunks/RAG); revisit if/when it's built.
    restated_by_accession: Mapped[str | None] = mapped_column(String(20))

    company: Mapped["Company"] = relationship()
