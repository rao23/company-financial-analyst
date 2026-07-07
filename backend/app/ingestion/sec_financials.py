"""Bulk-load financial_metrics from an SEC Financial Statement Data Set
quarterly zip (sec.gov/dera/data/financial-statement-data-sets.html).

Run with: python -m app.ingestion.sec_financials data/raw/2024q1.zip

Scope, deliberately: this ingests raw as-filed components only. EBITDA/FCF
are left NULL for the derivation layer (§6) to fill in separately, and
10-K/A restatement detection (was_restated) is not implemented yet — both
are follow-up steps, not oversights.
"""

import csv
import datetime
import sys
import zipfile
from io import TextIOWrapper

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import Company, FinancialMetric

RELEVANT_FORMS = {"10-K", "10-Q"}

# XBRL tag names for the same concept have changed over time as GAAP
# taxonomy evolved (e.g. ASC 606 revenue recognition, ~2018+). Try the
# modern tag first, fall back to older ones. See ADR-0005 for why values
# are further filtered to the filing's own primary period and the
# consolidated total (never a segment breakdown or comparative).
TAG_PRIORITY: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "eps": ["EarningsPerShareDiluted"],
    "operating_income": ["OperatingIncomeLoss"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditures": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}

ALL_TAGS = {tag for tags in TAG_PRIORITY.values() for tag in tags}


def parse_date(raw: str) -> datetime.date:
    return datetime.datetime.strptime(raw, "%Y%m%d").date()


def load_submissions(zf: zipfile.ZipFile, known_ciks: set[int]) -> dict[str, dict]:
    """adsh -> {cik, form, period, filed, fy, fp}.

    Filtered to 10-K/10-Q filed by a CIK already in our `companies` table —
    SEC's filer list includes plenty of companies without a current ticker
    (delisted, OTC, etc.) that company_tickers.json doesn't cover; skipping
    them here avoids a foreign-key failure on insert.
    """
    submissions = {}
    with zf.open("sub.txt") as raw:
        reader = csv.DictReader(TextIOWrapper(raw, encoding="utf-8"), delimiter="\t")
        for row in reader:
            if row["form"] not in RELEVANT_FORMS:
                continue
            cik = int(row["cik"])
            if cik not in known_ciks:
                continue
            submissions[row["adsh"]] = {
                "cik": cik,
                "form": row["form"],
                "period": parse_date(row["period"]),
                "filed": parse_date(row["filed"]),
                "fy": int(row["fy"]) if row["fy"] else None,
                "fp": row["fp"] or None,
            }
    return submissions


def load_facts(
    zf: zipfile.ZipFile, submissions: dict[str, dict]
) -> dict[tuple[int, datetime.date], dict]:
    """(cik, period) -> wide dict of as-filed fields, ready to insert."""
    facts: dict[tuple[int, datetime.date], dict] = {}
    tag_used: dict[tuple[int, datetime.date], dict[str, str]] = {}

    with zf.open("num.txt") as raw:
        reader = csv.DictReader(TextIOWrapper(raw, encoding="utf-8"), delimiter="\t")
        for row in reader:
            sub = submissions.get(row["adsh"])
            if sub is None:
                continue
            if row["tag"] not in ALL_TAGS:
                continue
            if row["segments"] or row["coreg"]:
                continue  # segment/co-registrant breakdown, not the consolidated total
            if parse_date(row["ddate"]) != sub["period"]:
                continue  # a comparative period, not this filing's own period
            if not row["value"]:
                continue  # genuine data-quality gap in SEC's bulk file (rare but real)

            key = (sub["cik"], sub["period"])
            row_facts = facts.setdefault(
                key,
                {
                    "form": sub["form"],
                    "fiscal_year": sub["fy"],
                    "fiscal_period": sub["fp"],
                    "source_accession_number": row["adsh"],
                    "filed_date": sub["filed"],
                },
            )
            used = tag_used.setdefault(key, {})

            for field, tags in TAG_PRIORITY.items():
                if row["tag"] not in tags:
                    continue
                current = used.get(field)
                if current is None or tags.index(row["tag"]) < tags.index(current):
                    row_facts[field] = float(row["value"])
                    used[field] = row["tag"]

    return facts


def load_financial_metrics(zip_path: str) -> None:
    db = SessionLocal()
    try:
        known_ciks = {cik for (cik,) in db.execute(select(Company.cik))}

        with zipfile.ZipFile(zip_path) as zf:
            submissions = load_submissions(zf, known_ciks)
            facts = load_facts(zf, submissions)

        before = db.execute(select(func.count()).select_from(FinancialMetric)).scalar_one()

        for (cik, period), row_facts in facts.items():
            stmt = (
                pg_insert(FinancialMetric)
                .values(company_cik=cik, period=period, **row_facts)
                .on_conflict_do_nothing(constraint="uq_financial_metric_period")
            )
            db.execute(stmt)
        db.commit()

        after = db.execute(select(func.count()).select_from(FinancialMetric)).scalar_one()
        print(
            f"Processed {len(facts)} (company, period) rows from {zip_path}, "
            f"inserted {after - before} new financial_metrics rows."
        )
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.ingestion.sec_financials <path-to-quarterly-zip>")
        sys.exit(1)
    load_financial_metrics(sys.argv[1])
