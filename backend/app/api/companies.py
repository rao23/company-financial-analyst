import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, CompanyAlias, PriceHistory

router = APIRouter(prefix="/companies", tags=["companies"])

# SEC's XBRL mandate phase-in took effect in 2009 — a fixed constant, not
# something inferred from how much of our own historical backlog we've
# ingested. See CONTEXT.md "Pre-2009 Coverage Gap" and DESIGN.md §12.
XBRL_MANDATE_DATE = datetime.date(2009, 1, 1)


class CompanySearchResult(BaseModel):
    cik: int
    ticker: str
    name: str


@router.get("/search", response_model=list[CompanySearchResult])
def search_companies(
    q: str = Query(..., min_length=1, description="Ticker, company name, or known alias"),
    limit: int = Query(10, le=50),
    db: Session = Depends(get_db),
) -> list[CompanySearchResult]:
    """Fuzzy company lookup for the search box's typeahead.

    Matches ticker/name/alias via ILIKE (v1 volume — ~8k SEC filers, a full
    scan is fine; see TASKS.md). `.ilike()` binds `q` as a query parameter,
    not string-interpolated SQL, so this is safe against injection by
    construction. Every result downstream of a user's *selection* here
    should key off `cik`, never re-run this fuzzy match.
    """
    substring_pattern = f"%{q}%"
    prefix_pattern = f"{q}%"

    # Tiered relevance, cheapest thing that beats "arbitrary scan order":
    # exact ticker > ticker prefix > name prefix > everything else (includes
    # alias matches and coincidental substrings like "apple" in "pineapple").
    # Depends only on Company columns, so it's constant across the
    # alias-join fan-out — safe to combine with DISTINCT below.
    rank = case(
        (Company.ticker.ilike(q), 0),
        (Company.ticker.ilike(prefix_pattern), 1),
        (Company.name.ilike(prefix_pattern), 2),
        else_=3,
    )

    stmt = (
        select(Company.cik, Company.ticker, Company.name, rank.label("rank"))
        .distinct()
        .outerjoin(CompanyAlias, CompanyAlias.company_cik == Company.cik)
        .where(
            or_(
                Company.ticker.ilike(prefix_pattern),
                Company.name.ilike(substring_pattern),
                CompanyAlias.alias.ilike(substring_pattern),
            )
        )
        .order_by(rank, Company.name)
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return [CompanySearchResult(cik=r.cik, ticker=r.ticker, name=r.name) for r in rows]


class CompanyDetail(BaseModel):
    cik: int
    ticker: str
    name: str
    sector: str | None
    gics: str | None
    ipo_date: datetime.date | None
    price_coverage_start: datetime.date | None
    has_pre_2009_gap: bool | None


@router.get("/{cik}", response_model=CompanyDetail)
def get_company(cik: int, db: Session = Depends(get_db)) -> CompanyDetail:
    """Company header info for the record page, including the Pre-2009
    Coverage Gap flag (§12) — computed from price_history's earliest date
    vs. the fixed XBRL mandate date, not stored on the Company row.
    `has_pre_2009_gap` is None (unknown), not False, when we have no price
    history for this company yet — that's a different state from "checked
    and there's no gap."
    """
    company = db.get(Company, cik)
    if company is None:
        raise HTTPException(status_code=404, detail=f"No company with CIK {cik}")

    price_coverage_start = db.execute(
        select(func.min(PriceHistory.date)).where(PriceHistory.company_cik == cik)
    ).scalar_one()

    has_pre_2009_gap = (
        price_coverage_start < XBRL_MANDATE_DATE if price_coverage_start is not None else None
    )

    return CompanyDetail(
        cik=company.cik,
        ticker=company.ticker,
        name=company.name,
        sector=company.sector,
        gics=company.gics,
        ipo_date=company.ipo_date,
        price_coverage_start=price_coverage_start,
        has_pre_2009_gap=has_pre_2009_gap,
    )
