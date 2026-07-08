"""Agent tools (DESIGN.md §8): the data-access layer the LangGraph agent
calls. Each function takes an explicit `db: Session` (same convention as
app.rag.retrieval.search_filing_chunks) rather than opening its own
session, so tests can pass the shared test-DB session directly. LangGraph
tool bindings (app/agent/graph.py) wrap these in thin `@tool`-decorated
functions that open/close a session per call.
"""

import datetime
import re
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, FinancialMetric, NewsArticle, NewsChunk, PriceHistory
from app.rag.retrieval import search_filing_chunks

# See CONTEXT.md "Trend Start": short-lived counter-moves under this
# threshold don't reset the swing-point search. 5% is a first-pass value,
# not yet tuned against real data -- Phase 5's hand-labeled eval cases
# (Trend Start Accuracy metric) are what this should actually be
# calibrated against, per TASKS.md's explicit callout. Revisit once those
# exist rather than trusting this number blindly.
TREND_REVERSAL_THRESHOLD_PCT = 0.05

_QUARTER_PATTERN = re.compile(r"^(\d{4})(Q[1-4]|FY)$")


def _get_company_by_ticker(db: Session, ticker: str) -> Company:
    company = db.execute(select(Company).where(Company.ticker == ticker.upper())).scalar_one_or_none()
    if company is None:
        raise ValueError(f"No company found for ticker {ticker!r}")
    return company


def _get_prices_up_to(db: Session, company_cik: int, date: datetime.date, limit: int | None = None) -> list[tuple[datetime.date, float]]:
    """Returns [(date, close), ...] ordered most-recent-first, for dates <= `date`."""
    stmt = (
        select(PriceHistory.date, PriceHistory.close)
        .where(PriceHistory.company_cik == company_cik, PriceHistory.date <= date)
        .order_by(PriceHistory.date.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).all())


def get_financials(db: Session, ticker: str, quarter: str) -> dict:
    """quarter is e.g. "2024Q1" or "2024FY"."""
    match = _QUARTER_PATTERN.match(quarter.upper())
    if not match:
        raise ValueError(f"quarter must look like '2024Q1' or '2024FY', got {quarter!r}")
    fiscal_year, fiscal_period = int(match.group(1)), match.group(2)

    company = _get_company_by_ticker(db, ticker)
    metric = db.execute(
        select(FinancialMetric).where(
            FinancialMetric.company_cik == company.cik,
            FinancialMetric.fiscal_year == fiscal_year,
            FinancialMetric.fiscal_period == fiscal_period,
        )
    ).scalar_one_or_none()
    if metric is None:
        return {"error": f"No financial_metrics row for {ticker} {quarter}"}

    return {
        "ticker": ticker.upper(),
        "fiscal_year": metric.fiscal_year,
        "fiscal_period": metric.fiscal_period,
        "period": metric.period.isoformat(),
        "filed_date": metric.filed_date.isoformat(),
        "form": metric.form,
        "revenue": metric.revenue,
        "eps": metric.eps,
        "ebitda": metric.ebitda,
        "fcf": metric.fcf,
        "operating_income": metric.operating_income,
        "depreciation_amortization": metric.depreciation_amortization,
        "operating_cash_flow": metric.operating_cash_flow,
        "capital_expenditures": metric.capital_expenditures,
    }


def get_filing_chunks(
    db: Session, ticker: str, date_from: datetime.date, date_to: datetime.date, query: str, top_k: int = 5
) -> list[dict]:
    """Company+date-range-filtered, then ranked by embedding similarity to
    `query` -- see app.rag.retrieval.search_filing_chunks. source_type is
    always "filing"/"official"."""
    company = _get_company_by_ticker(db, ticker)
    chunks = search_filing_chunks(db, company.cik, query, date_from, date_to, top_k=top_k)
    return [
        {
            "chunk_id": chunk.id,
            "section": chunk.section,
            "chunk_text": chunk.chunk_text,
            "source_type": chunk.source_type,
            "trust_level": chunk.trust_level,
            "form": chunk.filing.form,
            "filed_date": chunk.filing.filed_date.isoformat(),
            "source_url": chunk.filing.source_url,
        }
        for chunk in chunks
    ]


def get_news(db: Session, ticker: str, date_from: datetime.date, date_to: datetime.date) -> list[dict]:
    """Company+date-range-filtered listing, chronological -- no embedding
    ranking (unlike get_filing_chunks). News articles in a given window are
    few enough, and short enough, that the agent's own reasoning over the
    full set is more reliable than pre-filtering by similarity to a guessed
    query -- matches DESIGN.md's get_news(ticker, date_range) signature,
    which deliberately has no `query` parameter. source_type is always
    "news"/"unofficial".
    """
    company = _get_company_by_ticker(db, ticker)
    stmt = (
        select(NewsChunk, NewsArticle)
        .join(NewsArticle, NewsChunk.article_id == NewsArticle.id)
        .where(
            NewsArticle.company_cik == company.cik,
            NewsArticle.published_at >= datetime.datetime.combine(date_from, datetime.time.min, tzinfo=datetime.UTC),
            NewsArticle.published_at <= datetime.datetime.combine(date_to, datetime.time.max, tzinfo=datetime.UTC),
        )
        .order_by(NewsArticle.published_at)
    )
    rows = db.execute(stmt).all()
    return [
        {
            "chunk_id": chunk.id,
            "chunk_text": chunk.chunk_text,
            "source_type": chunk.source_type,
            "trust_level": chunk.trust_level,
            "headline": article.headline,
            "published_at": article.published_at.isoformat(),
            "source_url": article.source_url,
        }
        for chunk, article in rows
    ]


def get_price_context(db: Session, ticker: str, date: datetime.date) -> dict:
    """For a Move query: price change at `date` vs. a trailing 5-day average
    baseline (CONTEXT.md "Move") -- not a raw prior-day close, so a single
    noisy prior day doesn't distort what counts as "a big move."
    """
    company = _get_company_by_ticker(db, ticker)
    prices = _get_prices_up_to(db, company.cik, date, limit=6)  # investigation date + 5 prior
    if not prices or prices[0][0] != date:
        return {"error": f"No price_history row for {ticker} on {date.isoformat()}"}
    if len(prices) < 2:
        return {"error": f"Not enough price history before {date.isoformat()} to compute a baseline"}

    investigation_price = prices[0][1]
    baseline_prices = [close for _, close in prices[1:]]
    baseline_avg = sum(baseline_prices) / len(baseline_prices)
    pct_change = (investigation_price - baseline_avg) / baseline_avg

    return {
        "ticker": ticker.upper(),
        "date": date.isoformat(),
        "close": investigation_price,
        "baseline_5day_avg": baseline_avg,
        "pct_change_vs_baseline": pct_change,
    }


def _determine_recent_direction(prices_desc: list[tuple[datetime.date, float]]) -> Literal["up", "down"]:
    """Walks backward from the most recent price to find the most recent
    *different* price, and infers direction from that -- robust to an
    isolated flat/duplicate-value day rather than comparing only to the
    single immediately-prior price.
    """
    investigation_price = prices_desc[0][1]
    for _, price in prices_desc[1:]:
        if price < investigation_price:
            return "up"  # a lower price further back means the price has been rising into today
        if price > investigation_price:
            return "down"  # a higher price further back means the price has been falling into today
    return "down"  # degenerate case: every price on file is identical


def get_price_trend(db: Session, ticker: str, date: datetime.date) -> dict:
    """For a Trend query: walks backward from `date` to find the Trend
    Start (CONTEXT.md "Trend Start") -- the most recent swing point (local
    peak if declining, local trough if rising) before a reversal exceeding
    TREND_REVERSAL_THRESHOLD_PCT. Short counter-moves under that threshold
    are absorbed rather than resetting the search, so a one-day bounce
    during an overall decline doesn't get mistaken for the trend's start.

    Returns {direction, trend_start_date, cumulative_move_pct}.
    """
    company = _get_company_by_ticker(db, ticker)
    prices = _get_prices_up_to(db, company.cik, date)
    if not prices or prices[0][0] != date:
        return {"error": f"No price_history row for {ticker} on {date.isoformat()}"}
    if len(prices) < 2:
        return {"error": f"Not enough price history before {date.isoformat()} to determine a trend"}

    direction = _determine_recent_direction(prices)
    looking_for_peak = direction == "down"  # declining trend -> searching backward for a local peak

    running_extreme_date, running_extreme_price = prices[0]
    counter_move_extreme: float | None = None  # the most adverse price seen since the last new extreme

    for price_date, price in prices[1:]:
        is_new_extreme = price >= running_extreme_price if looking_for_peak else price <= running_extreme_price
        if is_new_extreme:
            running_extreme_date, running_extreme_price = price_date, price
            counter_move_extreme = None  # any prior counter-move is absorbed by this larger extreme
            continue

        if looking_for_peak:
            counter_move_extreme = price if counter_move_extreme is None else min(counter_move_extreme, price)
            reversal_pct = (running_extreme_price - counter_move_extreme) / running_extreme_price
        else:
            counter_move_extreme = price if counter_move_extreme is None else max(counter_move_extreme, price)
            reversal_pct = (counter_move_extreme - running_extreme_price) / running_extreme_price

        if reversal_pct > TREND_REVERSAL_THRESHOLD_PCT:
            break  # genuine reversal confirmed -- running_extreme is the Trend Start

    investigation_price = prices[0][1]
    cumulative_move_pct = (investigation_price - running_extreme_price) / running_extreme_price

    return {
        "ticker": ticker.upper(),
        "direction": direction,
        "trend_start_date": running_extreme_date.isoformat(),
        "cumulative_move_pct": cumulative_move_pct,
    }
