"""Tests for the LangGraph agent's control flow (app.agent.graph).

The LLM is fully scripted here -- these tests are about graph wiring
(force-widen, citation-rejection retry, max-rounds fallback, Grounding Set
accumulation), not model quality, which was already verified live against
the real Gemini API (see commit notes). Tool calls still hit the real
tool functions against the test database -- only embed_query and the LLM
itself are faked, matching the existing test_retrieval.py/test_agent_tools.py
pattern of faking the model boundary while keeping DB logic real.
"""

import datetime
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.agent import graph as agent_graph
from app.models import Company, Filing, FilingChunk
from app.models.filing import EMBEDDING_DIM


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _ai_message(*tool_calls: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=list(tool_calls))


def _install_fake_llm(monkeypatch, responses: list[AIMessage]) -> None:
    """Every agent_node call constructs a fresh ChatGoogleGenerativeAI, so
    the fake needs a class (not a single instance) that all share one
    response iterator."""
    iterator = iter(responses)

    class _FakeLLM:
        def __init__(self, **kwargs):
            pass

        def bind_tools(self, tools, tool_choice=None, **kwargs):
            return self

        def invoke(self, messages):
            return next(iterator)

    monkeypatch.setattr(agent_graph, "ChatGoogleGenerativeAI", _FakeLLM)


def _fresh_thread_id() -> str:
    return f"test-{uuid.uuid4()}"


@pytest.fixture(autouse=True)
def _mock_embed_query(monkeypatch):
    monkeypatch.setattr("app.rag.retrieval.embed_query", lambda query: [1.0] * EMBEDDING_DIM)


@pytest.fixture(autouse=True)
def _mock_classify_intent(monkeypatch):
    monkeypatch.setattr(agent_graph, "classify_query_intent", lambda question: "move")


def _seed_filing_chunk(db_session, cik=1, ticker="TEST") -> int:
    db_session.add(Company(cik=cik, ticker=ticker, name=f"{ticker} Inc"))
    filing = Filing(
        company_cik=cik,
        accession_number="acc-1",
        form="10-Q",
        period=datetime.date(2024, 1, 1),
        filed_date=datetime.date(2024, 1, 15),
        source_url="https://example.com/filing",
        raw_text="irrelevant",
    )
    db_session.add(filing)
    db_session.flush()
    chunk = FilingChunk(
        filing_id=filing.id,
        section="Item 1",
        chunk_index=0,
        chunk_text="Real grounded chunk text",
        embedding=[1.0] * EMBEDDING_DIM,
    )
    db_session.add(chunk)
    db_session.commit()
    return chunk.id


class TestHappyPath:
    def test_finds_a_grounded_chunk_and_submits_a_final_answer(self, db_session, monkeypatch):
        chunk_id = _seed_filing_chunk(db_session)

        _install_fake_llm(
            monkeypatch,
            [
                _ai_message(
                    _tool_call(
                        "get_filing_chunks_tool",
                        {"ticker": "TEST", "date_from": "2024-01-01", "date_to": "2024-06-01", "query": "anything"},
                        "call-1",
                    )
                ),
                _ai_message(
                    _tool_call(
                        "SubmitFinalAnswer",
                        {
                            "explanation": "Explained by the grounded chunk.",
                            "citations": [{"source_type": "filing", "source_id": f"filing:{chunk_id}", "quote": "Real grounded chunk text"}],
                            "lag_days": 0,
                            "magnitude_match": "strong",
                            "no_clear_cause": False,
                        },
                        "call-2",
                    )
                ),
            ],
        )

        answer = agent_graph.run_agent("TEST", "2024-06-01", "why did it move", _fresh_thread_id())

        assert answer.no_clear_cause is False
        assert answer.citations[0].source_id == f"filing:{chunk_id}"
        assert answer.confidence == pytest.approx(1.0)  # 14-day tier + filing + strong match


class TestForceWiden:
    def test_empty_retrieval_deterministically_widens_the_window_twice_then_lets_the_model_answer(self, db_session, monkeypatch):
        db_session.add(Company(cik=1, ticker="TEST", name="Test Inc"))
        db_session.commit()

        empty_news_call = lambda call_id: _ai_message(  # noqa: E731
            _tool_call("get_news_tool", {"ticker": "TEST", "date_from": "2024-05-01", "date_to": "2024-06-01"}, call_id)
        )

        _install_fake_llm(
            monkeypatch,
            [
                empty_news_call("call-1"),  # 14-day window: nothing found -> deterministic widen to 90
                empty_news_call("call-2"),  # 90-day window: nothing found -> deterministic widen to 180
                empty_news_call("call-3"),  # 180-day window: nothing found, but no wider tier exists
                _ai_message(
                    _tool_call(
                        "SubmitFinalAnswer",
                        {
                            "explanation": "No discoverable cause even at the widest window.",
                            "citations": [],
                            "lag_days": None,
                            "magnitude_match": "unclear",
                            "no_clear_cause": True,
                        },
                        "call-4",
                    )
                ),
            ],
        )

        answer = agent_graph.run_agent("TEST", "2024-06-01", "why did it move", _fresh_thread_id())

        assert answer.no_clear_cause is True
        assert answer.confidence is None


class TestCitationRejection:
    def test_ungrounded_citation_is_rejected_and_the_model_gets_a_chance_to_retry(self, db_session, monkeypatch):
        db_session.add(Company(cik=1, ticker="TEST", name="Test Inc"))
        db_session.commit()

        _install_fake_llm(
            monkeypatch,
            [
                _ai_message(
                    _tool_call(
                        "SubmitFinalAnswer",
                        {
                            "explanation": "Citing something never retrieved.",
                            "citations": [{"source_type": "filing", "source_id": "filing:999", "quote": "fabricated"}],
                            "lag_days": 0,
                            "magnitude_match": "strong",
                            "no_clear_cause": False,
                        },
                        "call-1",
                    )
                ),
                _ai_message(
                    _tool_call(
                        "SubmitFinalAnswer",
                        {
                            "explanation": "Retracting -- no clear cause found.",
                            "citations": [],
                            "lag_days": None,
                            "magnitude_match": "unclear",
                            "no_clear_cause": True,
                        },
                        "call-2",
                    )
                ),
            ],
        )

        answer = agent_graph.run_agent("TEST", "2024-06-01", "why did it move", _fresh_thread_id())

        assert answer.no_clear_cause is True  # the first (ungrounded) attempt never became the final answer


class TestMaxRounds:
    def test_gives_up_gracefully_after_max_rounds_without_a_grounded_answer(self, db_session, monkeypatch):
        db_session.add(Company(cik=1, ticker="TEST", name="Test Inc"))
        db_session.commit()

        # A tool call that never resolves to SubmitFinalAnswer, repeated
        # past MAX_ROUNDS -- get_financials_tool with no matching quarter
        # just returns an error dict each time, never advancing the state.
        responses = [
            _ai_message(_tool_call("get_financials_tool", {"ticker": "TEST", "quarter": "2024Q1"}, f"call-{i}"))
            for i in range(agent_graph.MAX_ROUNDS + 2)
        ]
        _install_fake_llm(monkeypatch, responses)

        answer = agent_graph.run_agent("TEST", "2024-06-01", "why did it move", _fresh_thread_id())

        assert answer.no_clear_cause is True
        assert answer.confidence is None


class TestGroundingSetAccumulation:
    def test_grounding_set_persists_across_a_follow_up_in_the_same_thread(self, db_session, monkeypatch):
        chunk_id = _seed_filing_chunk(db_session)
        thread_id = _fresh_thread_id()

        _install_fake_llm(
            monkeypatch,
            [
                _ai_message(
                    _tool_call(
                        "get_filing_chunks_tool",
                        {"ticker": "TEST", "date_from": "2024-01-01", "date_to": "2024-06-01", "query": "anything"},
                        "call-1",
                    )
                ),
                _ai_message(
                    _tool_call(
                        "SubmitFinalAnswer",
                        {
                            "explanation": "First answer.",
                            "citations": [{"source_type": "filing", "source_id": f"filing:{chunk_id}", "quote": "Real grounded chunk text"}],
                            "lag_days": 0,
                            "magnitude_match": "strong",
                            "no_clear_cause": False,
                        },
                        "call-2",
                    )
                ),
            ],
        )
        agent_graph.run_agent("TEST", "2024-06-01", "why did it move", thread_id)

        # Follow-up: cites the same chunk WITHOUT re-retrieving it -- only
        # possible if the Grounding Set carried over from the first turn.
        _install_fake_llm(
            monkeypatch,
            [
                _ai_message(
                    _tool_call(
                        "SubmitFinalAnswer",
                        {
                            "explanation": "Follow-up, reusing the earlier citation.",
                            "citations": [{"source_type": "filing", "source_id": f"filing:{chunk_id}", "quote": "Real grounded chunk text"}],
                            "lag_days": 0,
                            "magnitude_match": "strong",
                            "no_clear_cause": False,
                        },
                        "call-3",
                    )
                ),
            ],
        )
        follow_up_answer = agent_graph.run_agent("TEST", "2024-06-01", "anything else?", thread_id)

        assert follow_up_answer.no_clear_cause is False
        assert follow_up_answer.citations[0].source_id == f"filing:{chunk_id}"
