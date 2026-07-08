"""Tests for price history ingestion (app.ingestion.price_history).

yfinance is mocked out -- these tests are about our own insert/idempotency
logic, not Yahoo's data or network behavior.
"""

import datetime

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.ingestion.price_history import load_price_history
from app.models import Company, PriceHistory


class _FakeTicker:
    def __init__(self, history_df: pd.DataFrame):
        self._history_df = history_df

    def history(self, period: str) -> pd.DataFrame:
        return self._history_df


def _fake_history(rows: list[tuple[str, float, int]]) -> pd.DataFrame:
    index = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame({"Close": [r[1] for r in rows], "Volume": [r[2] for r in rows]}, index=index)


def _mock_yfinance(monkeypatch, history_df: pd.DataFrame):
    monkeypatch.setattr(
        "app.ingestion.price_history.yf.Ticker", lambda ticker: _FakeTicker(history_df)
    )


def test_no_company_found_does_not_error(db_session, monkeypatch):
    _mock_yfinance(monkeypatch, _fake_history([("2024-01-02", 100.0, 1000)]))
    load_price_history("NOPE")  # no Company row for this ticker
    assert db_session.execute(select(func.count()).select_from(PriceHistory)).scalar_one() == 0


def test_empty_yfinance_response_does_not_error(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    db_session.commit()

    _mock_yfinance(monkeypatch, pd.DataFrame())
    load_price_history("AAPL")

    assert db_session.execute(select(func.count()).select_from(PriceHistory)).scalar_one() == 0


def test_inserts_one_row_per_price_bar(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    db_session.commit()

    _mock_yfinance(
        monkeypatch,
        _fake_history([("2024-01-02", 185.64, 82488700), ("2024-01-03", 184.25, 58414500)]),
    )
    load_price_history("AAPL")

    rows = db_session.execute(
        select(PriceHistory).where(PriceHistory.company_cik == 1).order_by(PriceHistory.date)
    ).scalars().all()
    assert [r.date for r in rows] == [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]
    assert rows[0].close == pytest.approx(185.64)
    assert rows[0].volume == 82488700


def test_rerunning_is_idempotent(db_session, monkeypatch):
    db_session.add(Company(cik=1, ticker="AAPL", name="Apple Inc."))
    db_session.commit()

    _mock_yfinance(monkeypatch, _fake_history([("2024-01-02", 185.64, 82488700)]))
    load_price_history("AAPL")
    load_price_history("AAPL")  # re-running against the same data must not duplicate rows

    count = db_session.execute(
        select(func.count()).select_from(PriceHistory).where(PriceHistory.company_cik == 1)
    ).scalar_one()
    assert count == 1
