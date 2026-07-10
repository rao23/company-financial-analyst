"""Tests for the agent's data-access tools (app.agent.tools)."""

import datetime

import pytest

from app.agent.tools import (
    TREND_REVERSAL_THRESHOLD_PCT,
    get_filing_chunks,
    get_financials,
    get_news,
    get_price_context,
    get_price_trend,
)
from app.models import Company, Filing, FilingChunk, FinancialMetric, NewsArticle, NewsChunk, PriceHistory
from app.models.filing import EMBEDDING_DIM


def _make_company(db_session, cik=1, ticker="TEST") -> Company:
    company = Company(cik=cik, ticker=ticker, name=f"{ticker} Inc")
    db_session.add(company)
    db_session.commit()
    return company


def _add_prices(db_session, cik: int, prices: list[tuple[datetime.date, float]]) -> None:
    for date, close in prices:
        db_session.add(PriceHistory(company_cik=cik, date=date, close=close, volume=1000))
    db_session.commit()


class TestGetFinancials:
    def test_returns_the_matching_quarter(self, db_session):
        _make_company(db_session)
        db_session.add(
            FinancialMetric(
                company_cik=1,
                period=datetime.date(2023, 12, 30),
                fiscal_year=2024,
                fiscal_period="Q1",
                form="10-Q",
                revenue=119575000000.0,
                ebitda=43200000000.0,
                fcf=37500000000.0,
                source_accession_number="acc-1",
                filed_date=datetime.date(2024, 2, 1),
            )
        )
        db_session.commit()

        result = get_financials(db_session, "TEST", "2024Q1")

        assert result["revenue"] == 119575000000.0
        assert result["ebitda"] == 43200000000.0
        assert result["filed_date"] == "2024-02-01"

    def test_missing_quarter_returns_an_error_dict(self, db_session):
        _make_company(db_session)
        result = get_financials(db_session, "TEST", "2024Q1")
        assert "error" in result

    def test_invalid_quarter_format_raises(self, db_session):
        _make_company(db_session)
        with pytest.raises(ValueError, match="quarter must look like"):
            get_financials(db_session, "TEST", "not-a-quarter")

    def test_unknown_ticker_raises(self, db_session):
        with pytest.raises(ValueError, match="No company found"):
            get_financials(db_session, "NOPE", "2024Q1")


class TestGetFilingChunks:
    @pytest.fixture(autouse=True)
    def _mock_embed_query(self, monkeypatch):
        monkeypatch.setattr("app.rag.retrieval.embed_query", lambda query: [1.0] * EMBEDDING_DIM)

    def test_returns_chunks_with_filing_metadata(self, db_session):
        _make_company(db_session)
        filing = Filing(
            company_cik=1,
            accession_number="acc-1",
            form="10-Q",
            period=datetime.date(2024, 1, 1),
            filed_date=datetime.date(2024, 2, 1),
            source_url="https://example.com/filing",
            raw_text="irrelevant",
        )
        db_session.add(filing)
        db_session.flush()
        db_session.add(
            FilingChunk(
                filing_id=filing.id, section="Item 1", chunk_index=0, chunk_text="some filing text", embedding=[1.0] * EMBEDDING_DIM
            )
        )
        db_session.commit()

        results = get_filing_chunks(
            db_session, "TEST", datetime.date(2024, 1, 1), datetime.date(2024, 6, 30), query="anything"
        )

        assert len(results) == 1
        assert results[0]["chunk_text"] == "some filing text"
        assert results[0]["source_type"] == "filing"
        assert results[0]["form"] == "10-Q"
        assert results[0]["source_url"] == "https://example.com/filing"

    def test_unknown_ticker_raises(self, db_session):
        with pytest.raises(ValueError, match="No company found"):
            get_filing_chunks(db_session, "NOPE", datetime.date(2024, 1, 1), datetime.date(2024, 6, 30), query="q")

    def test_inverted_date_range_raises(self, db_session):
        _make_company(db_session)
        with pytest.raises(ValueError, match="must not be after"):
            get_filing_chunks(db_session, "TEST", datetime.date(2024, 1, 1), datetime.date(2023, 1, 1), query="q")

    def test_date_range_exceeding_max_width_raises(self, db_session):
        _make_company(db_session)
        with pytest.raises(ValueError, match="exceeds the 200-day maximum"):
            get_filing_chunks(db_session, "TEST", datetime.date(2020, 1, 1), datetime.date(2024, 1, 1), query="q")


class TestGetNews:
    def test_returns_articles_within_range_in_chronological_order(self, db_session):
        _make_company(db_session)
        earlier = NewsArticle(
            company_cik=1, source_name="finnhub", external_id="1", published_at=datetime.datetime(2024, 1, 5, tzinfo=datetime.UTC),
            headline="Earlier", body="b", source_url="https://example.com/1",
        )
        later = NewsArticle(
            company_cik=1, source_name="finnhub", external_id="2", published_at=datetime.datetime(2024, 1, 20, tzinfo=datetime.UTC),
            headline="Later", body="b", source_url="https://example.com/2",
        )
        out_of_range = NewsArticle(
            company_cik=1, source_name="finnhub", external_id="3", published_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
            headline="Old", body="b", source_url="https://example.com/3",
        )
        db_session.add_all([earlier, later, out_of_range])
        db_session.flush()
        db_session.add_all(
            [
                NewsChunk(article_id=later.id, chunk_index=0, chunk_text="later chunk"),
                NewsChunk(article_id=earlier.id, chunk_index=0, chunk_text="earlier chunk"),
                NewsChunk(article_id=out_of_range.id, chunk_index=0, chunk_text="old chunk"),
            ]
        )
        db_session.commit()

        results = get_news(db_session, "TEST", datetime.date(2024, 1, 1), datetime.date(2024, 1, 31))

        assert [r["chunk_text"] for r in results] == ["earlier chunk", "later chunk"]
        assert all(r["source_type"] == "news" for r in results)

    def test_unknown_ticker_raises(self, db_session):
        with pytest.raises(ValueError, match="No company found"):
            get_news(db_session, "NOPE", datetime.date(2024, 1, 1), datetime.date(2024, 1, 31))

    def test_inverted_date_range_raises(self, db_session):
        _make_company(db_session)
        with pytest.raises(ValueError, match="must not be after"):
            get_news(db_session, "TEST", datetime.date(2024, 1, 31), datetime.date(2024, 1, 1))

    def test_date_range_exceeding_max_width_raises(self, db_session):
        _make_company(db_session)
        with pytest.raises(ValueError, match="exceeds the 200-day maximum"):
            get_news(db_session, "TEST", datetime.date(2020, 1, 1), datetime.date(2024, 1, 1))


class TestGetPriceContext:
    def test_computes_pct_change_vs_5day_baseline(self, db_session):
        _make_company(db_session)
        _add_prices(
            db_session, 1,
            [
                (datetime.date(2024, 1, 1), 100.0),
                (datetime.date(2024, 1, 2), 100.0),
                (datetime.date(2024, 1, 3), 100.0),
                (datetime.date(2024, 1, 4), 100.0),
                (datetime.date(2024, 1, 5), 100.0),
                (datetime.date(2024, 1, 8), 110.0),  # investigation date: +10% vs a flat 100 baseline
            ],
        )

        result = get_price_context(db_session, "TEST", datetime.date(2024, 1, 8))

        assert result["baseline_5day_avg"] == pytest.approx(100.0)
        assert result["pct_change_vs_baseline"] == pytest.approx(0.10)

    def test_missing_price_on_investigation_date_returns_error(self, db_session):
        _make_company(db_session)
        _add_prices(db_session, 1, [(datetime.date(2024, 1, 1), 100.0)])
        result = get_price_context(db_session, "TEST", datetime.date(2024, 1, 8))
        assert "error" in result

    def test_insufficient_history_returns_error(self, db_session):
        _make_company(db_session)
        _add_prices(db_session, 1, [(datetime.date(2024, 1, 8), 100.0)])
        result = get_price_context(db_session, "TEST", datetime.date(2024, 1, 8))
        assert "error" in result


class TestGetPriceTrend:
    def test_simple_monotonic_decline_finds_the_true_peak(self, db_session):
        _make_company(db_session)
        _add_prices(
            db_session, 1,
            [
                (datetime.date(2024, 1, 1), 100.0),
                (datetime.date(2024, 1, 2), 95.0),
                (datetime.date(2024, 1, 3), 90.0),
                (datetime.date(2024, 1, 4), 85.0),
                (datetime.date(2024, 1, 5), 80.0),
                (datetime.date(2024, 1, 8), 75.0),  # investigation date
            ],
        )

        result = get_price_trend(db_session, "TEST", datetime.date(2024, 1, 8))

        assert result["direction"] == "down"
        assert result["trend_start_date"] == "2024-01-01"
        assert result["cumulative_move_pct"] == pytest.approx(-0.25)

    def test_small_bounce_under_threshold_is_absorbed(self, db_session):
        # Forward in time: decline from 100 to 71.5, a one-day bounce up to
        # 75 (a 4.67% pullback when walking backward from 75 to 71.5,
        # under the 5% threshold), then the decline resumes down to 60.
        # The walk must see past the 75 bounce-top and find the true,
        # larger peak at 100 -- not stop at the smaller local peak.
        assert TREND_REVERSAL_THRESHOLD_PCT == 0.05  # test is calibrated against this specific threshold
        _make_company(db_session)
        _add_prices(
            db_session, 1,
            [
                (datetime.date(2024, 1, 1), 100.0),
                (datetime.date(2024, 1, 4), 92.0),
                (datetime.date(2024, 1, 7), 85.0),
                (datetime.date(2024, 1, 9), 78.0),
                (datetime.date(2024, 1, 11), 71.5),  # bottom just before the bounce
                (datetime.date(2024, 1, 12), 75.0),  # one-day bounce top
                (datetime.date(2024, 1, 13), 72.0),  # decline resumes
                (datetime.date(2024, 1, 15), 68.0),
                (datetime.date(2024, 1, 17), 65.0),
                (datetime.date(2024, 1, 19), 62.0),
                (datetime.date(2024, 1, 21), 60.0),  # investigation date
            ],
        )

        result = get_price_trend(db_session, "TEST", datetime.date(2024, 1, 21))

        assert result["direction"] == "down"
        assert result["trend_start_date"] == "2024-01-01"  # not 2024-01-12, the smaller local peak

    def test_reversal_exceeding_threshold_confirms_the_nearer_swing_point(self, db_session):
        # An 8% bounce (75 -> 69) exceeds the 5% threshold -- this must be
        # treated as a genuine reversal, confirming the nearer peak even
        # though a larger peak exists further back in the data.
        _make_company(db_session)
        _add_prices(
            db_session, 1,
            [
                (datetime.date(2024, 1, 1), 100.0),  # never reached -- walk stops before this
                (datetime.date(2024, 1, 2), 69.0),   # 8% bounce off the day-3 peak: confirms reversal
                (datetime.date(2024, 1, 3), 75.0),
                (datetime.date(2024, 1, 4), 70.0),
                (datetime.date(2024, 1, 5), 65.0),
                (datetime.date(2024, 1, 8), 60.0),   # investigation date
            ],
        )

        result = get_price_trend(db_session, "TEST", datetime.date(2024, 1, 8))

        assert result["trend_start_date"] == "2024-01-03"
        assert result["cumulative_move_pct"] == pytest.approx((60.0 - 75.0) / 75.0)

    def test_rising_trend_finds_the_true_trough(self, db_session):
        _make_company(db_session)
        _add_prices(
            db_session, 1,
            [
                (datetime.date(2024, 1, 1), 75.0),
                (datetime.date(2024, 1, 2), 80.0),
                (datetime.date(2024, 1, 3), 85.0),
                (datetime.date(2024, 1, 4), 90.0),
                (datetime.date(2024, 1, 5), 95.0),
                (datetime.date(2024, 1, 8), 100.0),  # investigation date
            ],
        )

        result = get_price_trend(db_session, "TEST", datetime.date(2024, 1, 8))

        assert result["direction"] == "up"
        assert result["trend_start_date"] == "2024-01-01"
        assert result["cumulative_move_pct"] == pytest.approx((100.0 - 75.0) / 75.0)

    def test_missing_price_on_investigation_date_returns_error(self, db_session):
        _make_company(db_session)
        _add_prices(db_session, 1, [(datetime.date(2024, 1, 1), 100.0)])
        result = get_price_trend(db_session, "TEST", datetime.date(2024, 1, 8))
        assert "error" in result

    def test_insufficient_history_returns_error(self, db_session):
        _make_company(db_session)
        _add_prices(db_session, 1, [(datetime.date(2024, 1, 8), 100.0)])
        result = get_price_trend(db_session, "TEST", datetime.date(2024, 1, 8))
        assert "error" in result
