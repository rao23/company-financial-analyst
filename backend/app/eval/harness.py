"""Offline eval harness runner (DESIGN.md §9): runs every hand-labeled
EvalCase through the real agent, scores it against all six metrics, and
writes EvalResult rows. Per CLAUDE.md, this is the merge gate -- run it
on every prompt/retrieval-logic/model change before treating that change
as an improvement.

Run with: python -m app.eval.harness
"""

import datetime

from sqlalchemy import select

from app.agent.graph import COMPILED_GRAPH, run_agent
from app.agent.tools import get_price_trend
from app.db import SessionLocal
from app.eval.judges import judge_faithfulness, judge_timing_awareness
from app.eval.metrics import (
    honesty_on_no_cause,
    numeric_consistency,
    retrieval_recall,
    trend_start_accuracy,
)
from app.models import Company, EvalCase, EvalResult, FinancialMetric

# Broad on purpose: an explanation could cite any of a company's known
# figures, not just the ones for the exact period under investigation.
_NUMERIC_FIELDS = [
    "revenue",
    "eps",
    "ebitda",
    "fcf",
    "operating_income",
    "depreciation_amortization",
    "operating_cash_flow",
    "capital_expenditures",
]

_MOVE_QUESTION = "Why did the stock move on this day?"
_TREND_QUESTION = "Why is the stock trending in this direction?"


def _known_financial_values(db, company_cik: int) -> list[float]:
    rows = db.execute(select(FinancialMetric).where(FinancialMetric.company_cik == company_cik)).scalars().all()
    return [
        value
        for row in rows
        for field in _NUMERIC_FIELDS
        if (value := getattr(row, field)) is not None
    ]


def run_eval_case(db, case: EvalCase, run_id: str) -> EvalResult:
    company = db.get(Company, case.company_cik)
    thread_id = f"eval-{run_id}-{case.id}"
    question = _TREND_QUESTION if case.query_type == "trend" else _MOVE_QUESTION

    answer = run_agent(company.ticker, case.investigation_date.isoformat(), question, thread_id)
    grounding_set = COMPILED_GRAPH.get_state({"configurable": {"thread_id": thread_id}}).values.get("grounding_set", {})

    retrieval_hit = retrieval_recall(case.expected_source_ref, grounding_set) if case.expected_source_ref else None

    known_values = _known_financial_values(db, case.company_cik)
    numeric_ok = numeric_consistency(answer.explanation, known_values)

    trend_start_date_str = None
    trend_ok = None
    if case.query_type == "trend":
        trend_result = get_price_trend(db, company.ticker, case.investigation_date)
        trend_start_date_str = trend_result.get("trend_start_date")
        if trend_start_date_str and case.expected_trend_start_min and case.expected_trend_start_max:
            trend_ok = trend_start_accuracy(
                datetime.date.fromisoformat(trend_start_date_str),
                case.expected_trend_start_min,
                case.expected_trend_start_max,
            )

    honesty_ok = honesty_on_no_cause(case.expected_cause_type, answer.no_clear_cause)

    source_chunks = [chunk["chunk_text"] for chunk in grounding_set.values()]
    faithfulness = judge_faithfulness(question, answer.explanation, source_chunks)
    timing = judge_timing_awareness(
        case.investigation_date.isoformat(), case.query_type, answer.explanation, answer.lag_days, trend_start_date_str
    )
    timing_ok = timing.lag_correct and timing.cause_correctly_attributed

    result = EvalResult(
        eval_case_id=case.id,
        run_id=run_id,
        retrieval_hit=retrieval_hit,
        faithfulness_score=1.0 if faithfulness.every_claim_grounded else 0.0,
        numeric_consistency=numeric_ok,
        timing_correct=timing_ok,
        trend_start_accuracy=trend_ok,
        honesty_correct=honesty_ok,
        run_date=datetime.datetime.now(tz=datetime.UTC),
    )
    db.add(result)
    db.commit()

    print(
        f"Case {case.id} ({company.ticker}, {case.query_type}): "
        f"retrieval_hit={retrieval_hit} numeric_ok={numeric_ok} "
        f"faithfulness={faithfulness.every_claim_grounded} timing_ok={timing_ok} "
        f"trend_start_accuracy={trend_ok} honesty_ok={honesty_ok}"
    )
    if not honesty_ok:
        print(f"  Honesty failure: expected_cause_type={case.expected_cause_type!r}, agent no_clear_cause={answer.no_clear_cause}")
    if faithfulness.unsupported_claims:
        print(f"  Unsupported claims: {faithfulness.unsupported_claims}")

    return result


def run_offline_suite() -> None:
    run_id = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d-%H%M%S")
    db = SessionLocal()
    try:
        cases = db.execute(select(EvalCase)).scalars().all()
        print(f"Running offline eval suite ({len(cases)} cases), run_id={run_id}")
        for case in cases:
            try:
                run_eval_case(db, case, run_id)
            except Exception as e:
                print(f"Case {case.id} failed to run: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    run_offline_suite()
