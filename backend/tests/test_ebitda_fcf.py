"""Tests for EBITDA/FCF derivation (app.derivation.ebitda_fcf)."""

import datetime

from app.derivation.ebitda_fcf import compute_ebitda_fcf
from app.models import Company, FinancialMetric

PERIOD = datetime.date(2024, 1, 1)
FILED_DATE = datetime.date(2024, 2, 1)


def _make_metric(db_session, **overrides) -> FinancialMetric:
    db_session.merge(Company(cik=1, ticker="TEST", name="Test Co"))
    fields = {
        "company_cik": 1,
        "period": PERIOD,
        "fiscal_year": 2024,
        "fiscal_period": "Q1",
        "form": "10-Q",
        "operating_income": 100.0,
        "depreciation_amortization": 20.0,
        "operating_cash_flow": 150.0,
        "capital_expenditures": 30.0,
        "source_accession_number": "acc-1",
        "filed_date": FILED_DATE,
        **overrides,
    }
    metric = FinancialMetric(**fields)
    db_session.add(metric)
    db_session.commit()
    return metric


def test_computes_ebitda_and_fcf_when_all_components_present(db_session):
    metric = _make_metric(db_session)

    compute_ebitda_fcf()

    db_session.refresh(metric)
    assert metric.ebitda == 120.0
    assert metric.fcf == 120.0


def test_leaves_ebitda_null_when_a_component_is_missing(db_session):
    metric = _make_metric(db_session, depreciation_amortization=None)

    compute_ebitda_fcf()

    db_session.refresh(metric)
    assert metric.ebitda is None
    assert metric.fcf == 120.0  # FCF components were still complete


def test_is_safe_to_rerun(db_session):
    metric = _make_metric(db_session)

    compute_ebitda_fcf()
    compute_ebitda_fcf()  # re-running on already-derived rows must not error or change the result

    db_session.refresh(metric)
    assert metric.ebitda == 120.0
    assert metric.fcf == 120.0
