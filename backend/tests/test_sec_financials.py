"""Tests for XBRL fact selection (app.ingestion.sec_financials).

load_submissions/load_facts take an already-open zipfile.ZipFile and plain
dicts -- no DB access -- so these are exercised directly against small
in-memory zips shaped like a real SEC Financial Statement Data Set,
without touching Postgres or downloading anything.

Field lists are the minimal set load_submissions/load_facts actually
read via DictReader -- not the full real sub.txt/num.txt schema.
"""

import io
import zipfile

import pytest

from app.ingestion.sec_financials import load_facts, load_submissions

SUB_FIELDS = ["adsh", "cik", "form", "period", "filed", "fy", "fp"]
NUM_FIELDS = ["adsh", "tag", "segments", "coreg", "ddate", "value"]


def _tsv(rows: list[dict], fields: list[str]) -> str:
    lines = ["\t".join(fields)]
    for row in rows:
        lines.append("\t".join(str(row.get(f, "")) for f in fields))
    return "\n".join(lines)


def _make_zip(sub_rows: list[dict], num_rows: list[dict]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sub.txt", _tsv(sub_rows, SUB_FIELDS))
        zf.writestr("num.txt", _tsv(num_rows, NUM_FIELDS))
    buf.seek(0)
    return zipfile.ZipFile(buf)


BASE_SUB_ROW = {
    "adsh": "0000320193-24-000006",
    "cik": "320193",
    "form": "10-Q",
    "period": "20231230",
    "filed": "20240202",
    "fy": "2024",
    "fp": "Q1",
}


@pytest.fixture
def known_ciks():
    return {320193}


def test_load_submissions_filters_to_relevant_forms(known_ciks):
    zf = _make_zip(
        sub_rows=[BASE_SUB_ROW, {**BASE_SUB_ROW, "adsh": "acc-8k", "form": "8-K"}],
        num_rows=[],
    )
    submissions = load_submissions(zf, known_ciks)
    assert list(submissions.keys()) == [BASE_SUB_ROW["adsh"]]


def test_load_submissions_filters_to_known_ciks():
    zf = _make_zip(sub_rows=[BASE_SUB_ROW], num_rows=[])
    submissions = load_submissions(zf, known_ciks={999999})  # cik 320193 not in this set
    assert submissions == {}


def test_load_submissions_parses_dates_and_optional_fy_fp(known_ciks):
    zf = _make_zip(sub_rows=[{**BASE_SUB_ROW, "fy": "", "fp": ""}], num_rows=[])
    submissions = load_submissions(zf, known_ciks)
    sub = submissions[BASE_SUB_ROW["adsh"]]
    assert sub["period"].isoformat() == "2023-12-30"
    assert sub["filed"].isoformat() == "2024-02-02"
    assert sub["fy"] is None
    assert sub["fp"] is None


def _facts_for(num_rows, sub_rows=(BASE_SUB_ROW,), known_ciks=frozenset({320193})):
    zf = _make_zip(sub_rows=list(sub_rows), num_rows=num_rows)
    submissions = load_submissions(zf, known_ciks)
    return load_facts(zf, submissions)


def test_load_facts_picks_up_a_known_consolidated_tag():
    facts = _facts_for(
        [{"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20231230", "value": "119575000000"}]
    )
    ((_, revenue_row),) = facts.items()
    assert revenue_row["revenue"] == 119575000000.0


def test_load_facts_excludes_prior_year_comparative():
    # Same tag, but ddate doesn't match the filing's own period -- this is
    # the real Apple Q1 FY24 bug: the filing bundled a prior-year
    # comparative for the same tag in the same document.
    facts = _facts_for(
        [
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20231230", "value": "119575000000"},
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20221231", "value": "117154000000"},
        ]
    )
    ((_, revenue_row),) = facts.items()
    assert revenue_row["revenue"] == 119575000000.0


def test_load_facts_excludes_segment_breakdown_rows():
    facts = _facts_for(
        [
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "GreaterChinaSegment", "coreg": "", "ddate": "20231230", "value": "20819000000"},
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20231230", "value": "119575000000"},
        ]
    )
    ((_, revenue_row),) = facts.items()
    assert revenue_row["revenue"] == 119575000000.0


def test_load_facts_excludes_coregistrant_rows():
    facts = _facts_for(
        [
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "SomeSubsidiary", "ddate": "20231230", "value": "1000"},
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20231230", "value": "119575000000"},
        ]
    )
    ((_, revenue_row),) = facts.items()
    assert revenue_row["revenue"] == 119575000000.0


def test_load_facts_skips_rows_with_empty_value():
    facts = _facts_for(
        [{"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20231230", "value": ""}]
    )
    assert facts == {}


def test_load_facts_ignores_tags_outside_tag_priority():
    facts = _facts_for(
        [{"adsh": BASE_SUB_ROW["adsh"], "tag": "SomeIrrelevantTag", "segments": "", "coreg": "", "ddate": "20231230", "value": "42"}]
    )
    assert facts == {}


def test_load_facts_ignores_rows_referencing_an_unknown_accession():
    facts = _facts_for(
        [{"adsh": "not-a-real-accession", "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20231230", "value": "42"}]
    )
    assert facts == {}


def test_load_facts_prefers_higher_priority_tag_regardless_of_row_order():
    # "Revenues" is a lower-priority fallback than
    # "RevenueFromContractWithCustomerExcludingAssessedTax" -- the modern
    # tag must win even though it appears second in the file.
    facts = _facts_for(
        [
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "Revenues", "segments": "", "coreg": "", "ddate": "20231230", "value": "999"},
            {"adsh": BASE_SUB_ROW["adsh"], "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "segments": "", "coreg": "", "ddate": "20231230", "value": "119575000000"},
        ]
    )
    ((_, revenue_row),) = facts.items()
    assert revenue_row["revenue"] == 119575000000.0
