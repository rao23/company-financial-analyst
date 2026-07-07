"""Compute EBITDA/FCF for financial_metrics rows that have the raw
components but not the derived figures yet (§6).

Run with: python -m app.derivation.ebitda_fcf

    EBITDA ~= operating_income + depreciation_and_amortization
    FCF = operating_cash_flow - capital_expenditures

Both are pure functions of already-fixed as-filed components (never
restated, per ADR-0005), so unlike ingestion this is safe to just
recompute and overwrite on every run — the inputs never change, so
re-deriving from them can never produce a different answer.
"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FinancialMetric


def compute_ebitda_fcf() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(select(FinancialMetric)).scalars().all()
        ebitda_count = 0
        fcf_count = 0

        for row in rows:
            if row.operating_income is not None and row.depreciation_amortization is not None:
                row.ebitda = row.operating_income + row.depreciation_amortization
                ebitda_count += 1
            if row.operating_cash_flow is not None and row.capital_expenditures is not None:
                row.fcf = row.operating_cash_flow - row.capital_expenditures
                fcf_count += 1

        db.commit()
        print(
            f"Computed EBITDA for {ebitda_count}/{len(rows)} rows, "
            f"FCF for {fcf_count}/{len(rows)} rows."
        )
    finally:
        db.close()


if __name__ == "__main__":
    compute_ebitda_fcf()
