"""Investigation Date derivation (DESIGN.md §8).

The date passed into the agent depends on which chart series was clicked:
- Price series (daily): the clicked date is used as-is -- the market
  reacted to whatever happened on/before that exact day.
- Fundamentals point (quarterly): the period's filed_date is used, not
  the period-end date shown on the chart -- the market can't react to a
  number before it's disclosed, so period-end would send the
  expanding-window search hunting for causes before the information was
  even public.
"""

import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialMetric

ClickType = Literal["price", "fundamentals"]


def derive_investigation_date(
    db: Session, company_cik: int, click_type: ClickType, clicked_date: datetime.date
) -> datetime.date:
    """`clicked_date` is the daily price date for a "price" click, or the
    exact `period` value of the clicked quarter for a "fundamentals" click
    -- not an arbitrary date, since it has to match a real financial_metrics
    row to look up that filing's filed_date.
    """
    if click_type == "price":
        return clicked_date

    metric = db.execute(
        select(FinancialMetric).where(
            FinancialMetric.company_cik == company_cik,
            FinancialMetric.period == clicked_date,
        )
    ).scalar_one_or_none()
    if metric is None:
        raise ValueError(
            f"No financial_metrics row for company_cik={company_cik}, period={clicked_date} "
            "-- clicked_date for a fundamentals click must be an exact period value from that table."
        )
    return metric.filed_date
