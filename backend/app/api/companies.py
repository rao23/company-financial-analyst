from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, CompanyAlias

router = APIRouter(prefix="/companies", tags=["companies"])


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
