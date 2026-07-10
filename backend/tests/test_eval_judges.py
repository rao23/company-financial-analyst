"""Tests for the LLM-as-judge eval metrics (app.eval.judges).

The LLM is faked here -- these tests are about the wiring (structured
output plumbing, prompt formatting), not the judge's actual judgment
quality, which is a model-quality question a mock can't answer (same
reasoning as test_query_intent.py).
"""

from app.eval.judges import (
    FaithfulnessJudgment,
    TimingJudgment,
    judge_faithfulness,
    judge_timing_awareness,
)


class _FakeStructuredLLM:
    def __init__(self, result):
        self._result = result

    def invoke(self, messages):
        return self._result


class _FakeLLM:
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._result)


def test_judge_faithfulness_returns_the_llms_judgment():
    expected = FaithfulnessJudgment(every_claim_grounded=False, unsupported_claims=["claim X"])
    result = judge_faithfulness(
        question="why did it move",
        explanation="It moved because of claim X.",
        source_chunks=["some source text"],
        llm=_FakeLLM(expected),
    )
    assert result.every_claim_grounded is False
    assert result.unsupported_claims == ["claim X"]


def test_judge_timing_awareness_returns_the_llms_judgment():
    expected = TimingJudgment(lag_correct=True, cause_correctly_attributed=True, reasoning="dates line up")
    result = judge_timing_awareness(
        investigation_date="2024-09-10",
        query_type="move",
        explanation="Explained with a 1-day lag.",
        lag_days=1,
        llm=_FakeLLM(expected),
    )
    assert result.lag_correct is True
    assert result.cause_correctly_attributed is True
