"""Tests for company/alias ingestion (app.ingestion.sec_companies).

fetch_company_tickers is mocked with a small synthetic dataset shaped
like the real SEC file (dict of {cik_str, ticker, title} keyed by string
index) -- no network access in tests. The synthetic dataset deliberately
includes rows for every CURATED_ALIASES CIK, since inserting a curated
alias for a CIK that was never inserted as a Company would violate the
company_aliases -> companies foreign key.
"""

from sqlalchemy import select

from app.ingestion.sec_companies import CURATED_ALIASES, load_companies
from app.models import Company, CompanyAlias

FAKE_SEC_DATA = {
    "0": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
    "1": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
    "2": {"cik_str": 1652044, "ticker": "GOOGM", "title": "Alphabet Inc."},
    "3": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "4": {"cik_str": 1326801, "ticker": "META", "title": "Meta Platforms, Inc."},
    "5": {"cik_str": 1564408, "ticker": "SNAP", "title": "Snap Inc"},
    "6": {"cik_str": 764180, "ticker": "MO", "title": "Altria Group, Inc."},
    "7": {"cik_str": 39911, "ticker": "GPS", "title": "Gap Inc"},
}


def _run_load(monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.sec_companies.fetch_company_tickers", lambda: FAKE_SEC_DATA
    )
    load_companies()


def test_first_ticker_per_cik_becomes_canonical(db_session, monkeypatch):
    _run_load(monkeypatch)

    alphabet = db_session.get(Company, 1652044)
    assert alphabet.ticker == "GOOGL"  # first-encountered ticker for this CIK
    assert alphabet.name == "Alphabet Inc."


def test_extra_tickers_for_the_same_cik_become_aliases_not_companies(db_session, monkeypatch):
    _run_load(monkeypatch)

    assert db_session.get(Company, 1652044) is not None
    aliases = db_session.execute(
        select(CompanyAlias.alias).where(CompanyAlias.company_cik == 1652044)
    ).scalars().all()
    assert "GOOG" in aliases
    assert "GOOGM" in aliases
    assert "GOOGL" not in aliases  # the canonical ticker isn't duplicated as an alias


def test_single_ticker_company_gets_no_extra_alias(db_session, monkeypatch):
    _run_load(monkeypatch)

    apple_aliases = db_session.execute(
        select(CompanyAlias).where(CompanyAlias.company_cik == 320193)
    ).scalars().all()
    assert apple_aliases == []


def test_curated_aliases_are_inserted_for_every_entry(db_session, monkeypatch):
    _run_load(monkeypatch)

    for alias, cik in CURATED_ALIASES.items():
        row = db_session.execute(
            select(CompanyAlias).where(
                CompanyAlias.alias == alias, CompanyAlias.company_cik == cik
            )
        ).scalar_one_or_none()
        assert row is not None, f"expected curated alias {alias!r} -> {cik}"


def test_rerunning_load_is_idempotent(db_session, monkeypatch):
    _run_load(monkeypatch)
    company_count_first = db_session.execute(select(Company)).scalars().all()
    alias_count_first = db_session.execute(select(CompanyAlias)).scalars().all()

    _run_load(monkeypatch)  # re-running against the same data must not error or duplicate rows
    company_count_second = db_session.execute(select(Company)).scalars().all()
    alias_count_second = db_session.execute(select(CompanyAlias)).scalars().all()

    assert len(company_count_first) == len(company_count_second)
    assert len(alias_count_first) == len(alias_count_second)
