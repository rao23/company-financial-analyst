"""Fetch a filing's primary document text from EDGAR.

Given a company CIK and accession number (already known from the
financial_metrics ingestion's sub.txt data), looks up which file in the
filing is the actual primary document via SEC's submissions API — not a
guess from filename patterns, since exhibits live alongside it in the
same directory — then fetches it and strips HTML to plain text.
"""

import json
import re
import urllib.request

from bs4 import BeautifulSoup

USER_AGENT = "CompanyFinancialAnalyst research-project your-email@example.com"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as response:
        return response.read()


def get_filing_metadata(cik: int, accession_number: str) -> dict:
    """Look up a filing's form/period/filed-date/primary-document from
    SEC's submissions API — not filename guessing, since exhibits live
    alongside the primary document in the same directory.

    Note: SEC's submissions API only lists a company's most `recent`
    filings inline; older ones are paginated into separate files
    referenced by `filings.files` in the same JSON. Not handled here yet
    — fine for now since we're fetching a recent test filing, but a
    limitation worth knowing about before this is used for bulk backfill.

    `report_date` here can differ by a day or two from the `period` value
    financial_metrics stores for the same filing (from a different SEC
    bulk source, the Financial Statement Data Sets) — a real quirk of
    SEC's own data, not a bug. Not reconciled here; fine for RAG retrieval,
    which doesn't need day-exact period matching between the two tables.
    """
    padded_cik = f"{cik:010d}"
    data = json.loads(_get(f"https://data.sec.gov/submissions/CIK{padded_cik}.json"))
    recent = data["filings"]["recent"]
    for i, acc in enumerate(recent["accessionNumber"]):
        if acc == accession_number:
            return {
                "form": recent["form"][i],
                "report_date": recent["reportDate"][i],
                "filed_date": recent["filingDate"][i],
                "primary_document": recent["primaryDocument"][i],
            }
    raise ValueError(f"Accession {accession_number} not found in recent filings for CIK {cik}")


def list_filings_by_form(cik: int, form: str) -> list[dict]:
    """List every filing of a given form type (e.g. "8-K") for a CIK, from
    the same `recent` filings the submissions API exposes to
    get_filing_metadata. Same pagination caveat: `recent` only covers a
    company's most recent filings, not its full history — fine for now,
    same limitation as get_filing_metadata.
    """
    padded_cik = f"{cik:010d}"
    data = json.loads(_get(f"https://data.sec.gov/submissions/CIK{padded_cik}.json"))
    recent = data["filings"]["recent"]
    return [
        {
            "accession_number": recent["accessionNumber"][i],
            "report_date": recent["reportDate"][i],
            "filed_date": recent["filingDate"][i],
            "primary_document": recent["primaryDocument"][i],
        }
        for i, filed_form in enumerate(recent["form"])
        if filed_form == form
    ]


def fetch_filing_text(cik: int, accession_number: str, primary_document: str) -> tuple[str, str]:
    """Returns (raw_text, source_url). `primary_document` comes from
    get_filing_metadata — passed in rather than looked up again here so
    callers that already fetched metadata don't hit the submissions API
    twice."""
    accession_no_dashes = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_document}"

    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    # Modern filings are Inline XBRL — machine-readable tags embedded in the
    # same HTML as the human-readable text. <ix:header> holds every XBRL
    # context/unit definition (never meant to be visible), and individual
    # tagged facts without a natural place in the visual layout are wrapped
    # in display:none elements. Both pollute a naive get_text() with
    # metadata garbage instead of readable prose — strip them first.
    for tag in soup.find_all("ix:header"):
        tag.decompose()
    for tag in soup.find_all(style=lambda v: v and "display:none" in v.replace(" ", "")):
        tag.decompose()

    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse excessive blank lines from HTML whitespace
    return text.strip(), url
