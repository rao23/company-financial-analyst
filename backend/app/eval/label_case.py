"""Interactive CLI to hand-label EvalCase ground truth (DESIGN.md §9).

Ground truth is deliberately NOT auto-generated (per CLAUDE.md, eval
scoring/labeling is core judgment the human writes) -- this tool only
surfaces real candidates (filings/news near the investigation date, the
actual computed price move/trend) for a human to read and judge. You
still decide expected_cause_type and pick which candidate (if any) is the
real cause; this just removes the tedious/error-prone parts (finding
candidates, stripping dashes from accession numbers to match source_url).

Run with: python -m app.eval.label_case <TICKER> <YYYY-MM-DD> <move|trend>
"""

import datetime
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tools import get_news, get_price_context, get_price_trend
from app.db import SessionLocal
from app.models import Company, EvalCase, Filing

_WINDOW_TIERS_DAYS = [14, 90, 180]
_MAX_NEWS_DISPLAYED = 20


def _get_company(db: Session, ticker: str) -> Company:
    company = db.execute(select(Company).where(Company.ticker == ticker.upper())).scalar_one_or_none()
    if company is None:
        raise ValueError(f"No company found for ticker {ticker!r}")
    return company


def _fetch_filings_in_window(db: Session, company_cik: int, date: datetime.date, window_days: int) -> list[Filing]:
    date_from = date - datetime.timedelta(days=window_days)
    stmt = (
        select(Filing)
        .where(Filing.company_cik == company_cik, Filing.filed_date >= date_from, Filing.filed_date <= date)
        .order_by(Filing.filed_date.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _dedupe_news_by_article(chunks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped = []
    for chunk in chunks:
        if chunk["source_url"] in seen:
            continue
        seen.add(chunk["source_url"])
        deduped.append(chunk)
    return deduped


def _rank_news_by_relevance(news: list[dict], company: Company) -> list[dict]:
    """Heavily-covered tickers (AAPL, NVDA, ...) get tagged on hundreds of
    "Magnificent Seven"-style roundup articles that only mention the
    company in passing -- company_cik-tagging alone isn't a relevance
    signal for them. Headline-mentions-the-company is a cheap, no-embedding
    proxy that pushes those roundups down without hiding them entirely.
    """
    name_token = company.name.split()[0].lower()
    ticker_token = company.ticker.lower()

    def relevance_key(chunk: dict) -> tuple[int, str]:
        headline = chunk["headline"].lower()
        is_headline_relevant = name_token in headline or ticker_token in headline
        return (0 if is_headline_relevant else 1, chunk["published_at"])

    return sorted(news, key=relevance_key)


def _find_candidates(db: Session, company: Company, ticker: str, date: datetime.date) -> tuple[list[Filing], list[dict], int]:
    """Same expanding-window idea as the agent (DESIGN.md §8): try the
    narrowest window first, only widen if it comes up empty.
    """
    for window_days in _WINDOW_TIERS_DAYS:
        filings = _fetch_filings_in_window(db, company.cik, date, window_days)
        news = _rank_news_by_relevance(
            _dedupe_news_by_article(get_news(db, ticker, date - datetime.timedelta(days=window_days), date)),
            company,
        )
        if filings or news:
            return filings, news, window_days
    return [], [], _WINDOW_TIERS_DAYS[-1]


def _print_price_summary(query_type: str, price_info: dict) -> None:
    print("\n=== Price move ===")
    if "error" in price_info:
        print(f"  {price_info['error']}")
        return
    if query_type == "move":
        print(
            f"  {price_info['date']}: close={price_info['close']:.2f}, "
            f"vs 5-day baseline {price_info['baseline_5day_avg']:.2f} "
            f"({price_info['pct_change_vs_baseline']:+.2%})"
        )
    else:
        print(
            f"  direction={price_info['direction']}, trend_start={price_info['trend_start_date']}, "
            f"cumulative_move={price_info['cumulative_move_pct']:+.2%}"
        )


def _print_candidates(filings: list[Filing], news: list[dict], window_days: int) -> None:
    print(f"\n=== Candidates (within {window_days} days before the investigation date) ===")

    print("\nFilings:")
    if not filings:
        print("  (none)")
    for i, filing in enumerate(filings):
        print(f"  [F{i}] {filing.filed_date} {filing.form}  {filing.accession_number}")
        print(f"        {filing.source_url}")

    print("\nNews:")
    if not news:
        print("  (none)")
    shown, omitted = news[:_MAX_NEWS_DISPLAYED], news[_MAX_NEWS_DISPLAYED:]
    for i, chunk in enumerate(shown):
        snippet = chunk["chunk_text"][:200].replace("\n", " ")
        print(f"  [N{i}] {chunk['published_at']}  {chunk['headline']}")
        print(f"        {snippet}...")
        print(f"        {chunk['source_url']}")
    if omitted:
        print(f"  ... {len(omitted)} more, ranked lower (headline doesn't mention the company) -- not shown")


def _prompt_candidate_selection(filings: list[Filing], news: list[dict]) -> str | None:
    print(
        "\nWhich candidate is the real cause? Enter its label (e.g. 'F0' or 'N1'), "
        "or 'none' if no_clear_cause / the real cause isn't listed above."
    )
    while True:
        choice = input("> ").strip().upper()
        if choice == "NONE":
            return None
        if choice.startswith("F") and choice[1:].isdigit() and int(choice[1:]) < len(filings):
            return filings[int(choice[1:])].accession_number.replace("-", "")
        if choice.startswith("N") and choice[1:].isdigit() and int(choice[1:]) < len(news):
            return news[int(choice[1:])]["source_url"]
        print(f"  Not a valid selection: {choice!r}. Try again.")


def _prompt_for_label(query_type: str, computed_trend_start: str | None) -> tuple[str, str | None, datetime.date | None, datetime.date | None, str | None]:
    expected_cause_type = input(
        "\nexpected_cause_type (e.g. 'litigation', 'earnings', 'product_launch', 'no_clear_cause'): "
    ).strip()
    notes = input("notes (optional, blank to skip): ").strip() or None

    expected_trend_start_min = expected_trend_start_max = None
    if query_type == "trend":
        print(f"  (agent's own computed trend_start, for reference only: {computed_trend_start})")
        expected_trend_start_min = datetime.date.fromisoformat(input("expected_trend_start_min (YYYY-MM-DD): ").strip())
        expected_trend_start_max = datetime.date.fromisoformat(input("expected_trend_start_max (YYYY-MM-DD): ").strip())

    return expected_cause_type, notes, expected_trend_start_min, expected_trend_start_max


def label_case(ticker: str, investigation_date: datetime.date, query_type: str) -> None:
    db = SessionLocal()
    try:
        company = _get_company(db, ticker)

        price_info = (
            get_price_context(db, ticker, investigation_date)
            if query_type == "move"
            else get_price_trend(db, ticker, investigation_date)
        )
        _print_price_summary(query_type, price_info)
        computed_trend_start = price_info.get("trend_start_date")

        filings, news, window_days = _find_candidates(db, company, ticker, investigation_date)
        _print_candidates(filings, news, window_days)
        if not filings and not news:
            print("\n(no filings or news found even at the widest window -- likely a no_clear_cause case)")

        expected_source_ref = _prompt_candidate_selection(filings, news)
        expected_cause_type, notes, trend_min, trend_max = _prompt_for_label(query_type, computed_trend_start)

        case = EvalCase(
            company_cik=company.cik,
            investigation_date=investigation_date,
            query_type=query_type,
            expected_cause_type=expected_cause_type,
            expected_source_ref=expected_source_ref,
            expected_trend_start_min=trend_min,
            expected_trend_start_max=trend_max,
            notes=notes,
        )
        db.add(case)
        db.commit()
        print(f"\nSaved EvalCase id={case.id} for {ticker} {investigation_date.isoformat()} ({query_type}).")
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[3] not in ("move", "trend"):
        print("Usage: python -m app.eval.label_case <TICKER> <YYYY-MM-DD> <move|trend>")
        sys.exit(1)
    ticker, date_str, query_type = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        label_case(ticker, datetime.date.fromisoformat(date_str), query_type)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
