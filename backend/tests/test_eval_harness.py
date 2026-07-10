"""Tests for the eval harness runner (app.eval.harness).

The agent and the two LLM judges are mocked here -- their own correctness
is out of scope for this test (run_agent has its own tests; the judges'
wiring is covered in test_eval_judges.py). What's under test is harness
glue: does run_eval_case call the right things with the right arguments,
compute the right metrics against real DB rows, and persist a correct
EvalResult -- using the real test DB for Company/EvalCase/FinancialMetric.
"""

import datetime
from unittest.mock import patch

from app.agent.schemas import Citation, FinalAnswer
from app.eval.harness import run_eval_case
from app.eval.judges import FaithfulnessJudgment, TimingJudgment
from app.models import Company, EvalCase, EvalResult, FinancialMetric

_CITATION = Citation(source_type="filing", source_id="filing:1", quote="Revenue was $10 billion.")


def _make_company(db, cik=320193, ticker="AAPL"):
    company = Company(cik=cik, ticker=ticker, name="Apple Inc.")
    db.add(company)
    db.commit()
    return company


def _make_move_case(db, company_cik, expected_cause_type="litigation", expected_source_ref=None):
    case = EvalCase(
        company_cik=company_cik,
        investigation_date=datetime.date(2024, 3, 15),
        query_type="move",
        expected_cause_type=expected_cause_type,
        expected_source_ref=expected_source_ref,
    )
    db.add(case)
    db.commit()
    return case


def _patched_harness(*, final_answer, grounding_set, trend_result=None, faithfulness=None, timing=None):
    faithfulness = faithfulness or FaithfulnessJudgment(every_claim_grounded=True, unsupported_claims=[])
    timing = timing or TimingJudgment(lag_correct=True, cause_correctly_attributed=True, reasoning="ok")
    return (
        patch("app.eval.harness.run_agent", return_value=final_answer),
        patch(
            "app.eval.harness.COMPILED_GRAPH.get_state",
            return_value=type("_State", (), {"values": {"grounding_set": grounding_set}})(),
        ),
        patch("app.eval.harness.get_price_trend", return_value=trend_result or {}),
        patch("app.eval.harness.judge_faithfulness", return_value=faithfulness),
        patch("app.eval.harness.judge_timing_awareness", return_value=timing),
    )


class TestRunEvalCaseMove:
    def test_writes_an_eval_result_scored_against_real_db_rows(self, db_session):
        company = _make_company(db_session)
        db_session.add(
            FinancialMetric(
                company_cik=company.cik,
                period=datetime.date(2024, 3, 31),
                form="10-Q",
                revenue=10_000_000_000.0,
                source_accession_number="0000000000-24-000001",
                filed_date=datetime.date(2024, 4, 15),
            )
        )
        db_session.commit()
        case = _make_move_case(db_session, company.cik, expected_source_ref="000000000024000001")

        answer = FinalAnswer(
            explanation="Revenue was $10 billion, driven by a litigation settlement.",
            citations=[_CITATION],
            lag_days=2,
            confidence=0.8,
            no_clear_cause=False,
        )
        grounding_set = {
            "filing:1": {
                "chunk_text": "Revenue was $10 billion.",
                "source_url": "https://www.sec.gov/.../000000000024000001/doc.htm",
            }
        }
        patches = _patched_harness(final_answer=answer, grounding_set=grounding_set)
        with patches[0] as mock_run_agent, patches[1], patches[2], patches[3], patches[4]:
            result = run_eval_case(db_session, case, run_id="test-run-1")

        mock_run_agent.assert_called_once()
        called_args = mock_run_agent.call_args.args
        assert called_args[0] == company.ticker
        assert called_args[1] == case.investigation_date.isoformat()

        assert isinstance(result, EvalResult)
        assert result.eval_case_id == case.id
        assert result.retrieval_hit is True
        assert result.numeric_consistency is True
        assert result.faithfulness_score == 1.0
        assert result.timing_correct is True
        assert result.trend_start_accuracy is None
        assert result.honesty_correct is True

        persisted = db_session.get(EvalResult, result.id)
        assert persisted is not None
        assert persisted.run_id == "test-run-1"

    def test_flags_honesty_failure_when_agent_fabricates_a_cause(self, db_session):
        company = _make_company(db_session)
        case = _make_move_case(db_session, company.cik, expected_cause_type="no_clear_cause")

        answer = FinalAnswer(
            explanation="A minor product update caused the move.",
            citations=[_CITATION],
            lag_days=1,
            confidence=0.3,
            no_clear_cause=False,
        )
        patches = _patched_harness(final_answer=answer, grounding_set={})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = run_eval_case(db_session, case, run_id="test-run-2")

        assert result.honesty_correct is False
        assert result.retrieval_hit is None  # no expected_source_ref on this case


class TestRunEvalCaseTrend:
    def test_computes_trend_start_accuracy_from_get_price_trend_directly(self, db_session):
        company = _make_company(db_session)
        case = EvalCase(
            company_cik=company.cik,
            investigation_date=datetime.date(2024, 6, 1),
            query_type="trend",
            expected_cause_type="partnership",
            expected_trend_start_min=datetime.date(2024, 3, 1),
            expected_trend_start_max=datetime.date(2024, 3, 31),
        )
        db_session.add(case)
        db_session.commit()

        answer = FinalAnswer(
            explanation="A new partnership announced in March drove the rally.",
            citations=[_CITATION],
            lag_days=5,
            confidence=0.7,
            no_clear_cause=False,
        )
        patches = _patched_harness(
            final_answer=answer,
            grounding_set={},
            trend_result={"trend_start_date": "2024-03-15", "direction": "up", "cumulative_move_pct": 12.0},
        )
        with patches[0], patches[1], patches[2] as mock_trend, patches[3], patches[4]:
            result = run_eval_case(db_session, case, run_id="test-run-3")

        mock_trend.assert_called_once()
        assert result.trend_start_accuracy is True

    def test_trend_start_accuracy_stays_none_without_a_computed_trend_start(self, db_session):
        company = _make_company(db_session)
        case = EvalCase(
            company_cik=company.cik,
            investigation_date=datetime.date(2024, 6, 1),
            query_type="trend",
            expected_cause_type="partnership",
            expected_trend_start_min=datetime.date(2024, 3, 1),
            expected_trend_start_max=datetime.date(2024, 3, 31),
        )
        db_session.add(case)
        db_session.commit()

        answer = FinalAnswer(
            explanation="No trend start could be determined.",
            citations=[],
            lag_days=None,
            confidence=None,
            no_clear_cause=True,
        )
        patches = _patched_harness(final_answer=answer, grounding_set={}, trend_result={"trend_start_date": None})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = run_eval_case(db_session, case, run_id="test-run-4")

        assert result.trend_start_accuracy is None
