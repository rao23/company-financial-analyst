"""Tests for Query Intent classification (app.agent.query_intent).

The LLM is faked here -- these tests are about the wiring (structured
output plumbing, default construction), not the classification prompt's
actual judgment quality. The prompt itself is verified separately against
the real Gemini API (see the manual verification in the Phase 4 PR/commit
notes) since that's a model-quality question a mock can't answer.
"""

from app.agent.query_intent import QueryIntentClassification, classify_query_intent


class _FakeStructuredLLM:
    def __init__(self, intent: str):
        self._intent = intent

    def invoke(self, messages):
        return QueryIntentClassification(intent=self._intent)


class _FakeLLM:
    def __init__(self, intent: str):
        self._intent = intent

    def with_structured_output(self, schema):
        assert schema is QueryIntentClassification
        return _FakeStructuredLLM(self._intent)


def test_returns_move_when_the_llm_classifies_move():
    assert classify_query_intent("why did it drop here", llm=_FakeLLM("move")) == "move"


def test_returns_trend_when_the_llm_classifies_trend():
    assert classify_query_intent("why is it trending down", llm=_FakeLLM("trend")) == "trend"
