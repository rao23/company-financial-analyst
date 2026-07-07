import datetime

from sqlalchemy import BigInteger, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.company import Company  # noqa: F401 — resolves the relationship() string ref


class PriceHistory(Base):
    """One daily close/volume bar for a company."""

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("company_cik", "date", name="uq_price_history_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    date: Mapped[datetime.date]
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)

    company: Mapped["Company"] = relationship()
