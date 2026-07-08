"""Tests for Investigation Date derivation (app.agent.investigation_date)."""

import datetime

import pytest

from app.agent.investigation_date import derive_investigation_date
from app.models import Company, FinancialMetric


def test_price_click_uses_the_clicked_date_as_is(db_session):
    clicked_date = datetime.date(2024, 3, 15)
    result = derive_investigation_date(db_session, company_cik=1, click_type="price", clicked_date=clicked_date)
    assert result == clicked_date


def test_fundamentals_click_uses_filed_date_not_period(db_session):
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    period = datetime.date(2023, 12, 30)
    filed_date = datetime.date(2024, 2, 1)  # disclosed weeks after the period ended
    db_session.add(
        FinancialMetric(
            company_cik=1,
            period=period,
            fiscal_year=2024,
            fiscal_period="Q1",
            form="10-Q",
            source_accession_number="acc-1",
            filed_date=filed_date,
        )
    )
    db_session.commit()

    result = derive_investigation_date(db_session, company_cik=1, click_type="fundamentals", clicked_date=period)

    assert result == filed_date
    assert result != period  # the real bug this guards against: using period-end instead of filed_date


def test_fundamentals_click_with_no_matching_period_raises(db_session):
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    db_session.commit()

    with pytest.raises(ValueError, match="No financial_metrics row"):
        derive_investigation_date(
            db_session, company_cik=1, click_type="fundamentals", clicked_date=datetime.date(2023, 12, 30)
        )
