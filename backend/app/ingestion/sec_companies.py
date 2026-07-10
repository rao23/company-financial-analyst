"""Bulk-load companies + company_aliases from SEC's company_tickers.json.

Run with: python -m app.ingestion.sec_companies

Populates cik/ticker/name only — sector/gics/ipo_date aren't in this bulk
file (SEC doesn't publish GICS at all; it's an MSCI/S&P classification) and
are left NULL for now rather than guess-filled from an unreliable source.
"""

import json
import urllib.request

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Company, CompanyAlias

SEC_URL = "https://www.sec.gov/files/company_tickers.json"

# SEC blocks requests without a descriptive User-Agent identifying the requester.
USER_AGENT = "CompanyFinancialAnalyst research-project sid.rao2000@gmail.com"

# Curated brand-name -> legal-name mismatches (CONTEXT.md "Company Alias").
# No amount of fuzzy string matching gets from "Google" to "Alphabet Inc." —
# zero shared substring — so this has to be a hand-maintained lookup.
# CIKs verified against the live SEC file, not guessed.
CURATED_ALIASES: dict[str, int] = {
    "Google": 1652044,  # Alphabet Inc.
    "Facebook": 1326801,  # Meta Platforms, Inc.
    "Instagram": 1326801,
    "WhatsApp": 1326801,
    "Snapchat": 1564408,  # Snap Inc
    "Marlboro": 764180,  # Altria Group, Inc.
    "Old Navy": 39911,  # Gap Inc
    "Banana Republic": 39911,
}


def fetch_company_tickers() -> dict:
    req = urllib.request.Request(SEC_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def load_companies() -> None:
    raw = fetch_company_tickers()

    # SEC lists one row per ticker, but a company can have multiple share
    # classes under one CIK (e.g. Alphabet: GOOGL, GOOG, GOOGM, GOOGN).
    # companies.ticker is one-per-row, so the first ticker encountered per
    # CIK becomes canonical; any others become searchable aliases instead
    # of crashing on the unique constraint or being silently dropped.
    canonical: dict[int, dict] = {}
    extra_ticker_aliases: list[tuple[str, int]] = []

    for row in raw.values():
        cik = row["cik_str"]
        ticker = row["ticker"]
        if cik not in canonical:
            canonical[cik] = {"ticker": ticker, "name": row["title"]}
        else:
            extra_ticker_aliases.append((ticker, cik))

    db = SessionLocal()
    try:
        for cik, info in canonical.items():
            stmt = (
                pg_insert(Company)
                .values(cik=cik, ticker=info["ticker"], name=info["name"])
                .on_conflict_do_nothing(index_elements=["cik"])
            )
            db.execute(stmt)
        db.commit()

        for alias, cik in extra_ticker_aliases:
            stmt = (
                pg_insert(CompanyAlias)
                .values(alias=alias, company_cik=cik)
                .on_conflict_do_nothing(constraint="uq_company_alias")
            )
            db.execute(stmt)

        for alias, cik in CURATED_ALIASES.items():
            stmt = (
                pg_insert(CompanyAlias)
                .values(alias=alias, company_cik=cik)
                .on_conflict_do_nothing(constraint="uq_company_alias")
            )
            db.execute(stmt)

        db.commit()
        print(
            f"Loaded {len(canonical)} companies, "
            f"{len(extra_ticker_aliases)} extra-ticker aliases, "
            f"{len(CURATED_ALIASES)} curated aliases."
        )
    finally:
        db.close()


if __name__ == "__main__":
    load_companies()
