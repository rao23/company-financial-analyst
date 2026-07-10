"""Tests for the /companies API (app.api.companies).

Route functions are called directly with an explicit db session rather
than through a TestClient/ASGI app -- FastAPI's route decorators return
the endpoint function unmodified, so `search_companies(q=..., db=...)`
exercises exactly the same code a real request would hit.
"""

import datetime

import pytest
from fastapi import HTTPException

from app.api.companies import get_company, get_company_timeseries, search_companies
from app.models import Company, CompanyAlias, FinancialMetric, PriceHistory


def test_exact_ticker_match_ranks_above_coincidental_substring_match(db_session):
    # The real bug this guards against: searching "apple" surfaced "Maui
    # Land & Pineapple" *above* "Apple Inc." because a plain ILIKE has no
    # relevance concept. "Pineapple" legitimately contains "apple" as a
    # substring (pine+apple), so it's expected to still appear -- just
    # ranked below the exact ticker match, not excluded outright.
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    db_session.add(Company(cik=2, ticker="MLP", name="Maui Land & Pineapple"))
    db_session.commit()

    results = search_companies(q="apple", limit=10, db=db_session)

    assert [r.ticker for r in results] == ["AAPL", "MLP"]


def test_ticker_prefix_ranks_above_name_prefix(db_session):
    db_session.add(Company(cik=1, ticker="AAPL", name="Something Else Inc."))
    db_session.add(Company(cik=2, ticker="XYZ", name="AAPL Holdings"))
    db_session.commit()

    results = search_companies(q="AAPL", limit=10, db=db_session)

    assert [r.cik for r in results] == [1, 2]  # ticker match beats name match


def test_alias_match_surfaces_the_canonical_company(db_session):
    db_session.add(Company(cik=1652044, ticker="GOOGL", name="Alphabet Inc."))
    db_session.add(CompanyAlias(alias="Google", company_cik=1652044))
    db_session.commit()

    results = search_companies(q="Google", limit=10, db=db_session)

    assert [r.ticker for r in results] == ["GOOGL"]


def test_company_with_multiple_aliases_is_not_duplicated_in_results(db_session):
    # The real bug this guards against: the outer join to company_aliases
    # fans out one row per alias, producing duplicate companies in results
    # without an explicit DISTINCT.
    db_session.add(Company(cik=1652044, ticker="GOOGL", name="Alphabet Inc."))
    db_session.add(CompanyAlias(alias="GOOG", company_cik=1652044))
    db_session.add(CompanyAlias(alias="GOOGM", company_cik=1652044))
    db_session.commit()

    results = search_companies(q="Alphabet", limit=10, db=db_session)

    assert len(results) == 1


def test_search_respects_limit(db_session):
    for i in range(5):
        db_session.add(Company(cik=i, ticker=f"TIC{i}", name=f"Ticker Co {i}"))
    db_session.commit()

    results = search_companies(q="Ticker", limit=2, db=db_session)

    assert len(results) == 2


def test_get_company_404_for_unknown_cik(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_company(cik=999999, db=db_session)
    assert exc_info.value.status_code == 404


def test_pre_2009_gap_is_true_when_earliest_price_predates_mandate(db_session):
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    db_session.add(PriceHistory(company_cik=1, date=datetime.date(1980, 12, 12), close=1.0, volume=100))
    db_session.commit()

    detail = get_company(cik=1, db=db_session)

    assert detail.has_pre_2009_gap is True


def test_pre_2009_gap_is_false_when_coverage_starts_after_mandate(db_session):
    db_session.add(Company(cik=1, ticker="ABNB", name="Airbnb, Inc."))
    db_session.add(PriceHistory(company_cik=1, date=datetime.date(2020, 12, 10), close=1.0, volume=100))
    db_session.commit()

    detail = get_company(cik=1, db=db_session)

    assert detail.has_pre_2009_gap is False


def test_pre_2009_gap_is_none_when_no_price_history_ingested_yet(db_session):
    db_session.add(Company(cik=1, ticker="NEWCO", name="New Co"))
    db_session.commit()

    detail = get_company(cik=1, db=db_session)

    assert detail.has_pre_2009_gap is None  # genuinely unknown, not "no gap"


def test_timeseries_404_for_unknown_cik(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_company_timeseries(cik=999999, db=db_session)
    assert exc_info.value.status_code == 404


def test_timeseries_returns_prices_and_fundamentals_in_chronological_order(db_session):
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    db_session.add(PriceHistory(company_cik=1, date=datetime.date(2024, 1, 2), close=101.0, volume=100))
    db_session.add(PriceHistory(company_cik=1, date=datetime.date(2024, 1, 1), close=100.0, volume=100))
    db_session.add(
        FinancialMetric(
            company_cik=1,
            period=datetime.date(2024, 1, 1),
            fiscal_year=2024,
            fiscal_period="Q1",
            form="10-Q",
            revenue=100.0,
            ebitda=40.0,
            fcf=30.0,
            source_accession_number="acc-1",
            filed_date=datetime.date(2024, 2, 1),
        )
    )
    db_session.commit()

    result = get_company_timeseries(cik=1, db=db_session)

    assert [p.date for p in result.prices] == [datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)]
    assert result.fundamentals[0].revenue == 100.0
    assert result.fundamentals[0].ebitda == 40.0
