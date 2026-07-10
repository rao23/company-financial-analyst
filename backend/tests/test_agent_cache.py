"""Tests for the agent answer cache (app.agent.cache).

run_agent and the graph's checkpoint state are mocked -- this is about the
caching wrapper's own logic (hit/miss/versioning/follow-up bypass), not
the agent's own correctness, which has its own tests.
"""

import datetime
from unittest.mock import patch

from app.agent.cache import PROMPT_VERSION, get_cached_or_run_agent
from app.agent.schemas import FinalAnswer
from app.models import AgentAnswerCache, Company

_ANSWER = FinalAnswer(explanation="A cause.", citations=[], lag_days=1, confidence=0.8, no_clear_cause=False)


def _make_company(db_session, cik=1, ticker="TEST") -> Company:
    company = Company(cik=cik, ticker=ticker, name=f"{ticker} Inc")
    db_session.add(company)
    db_session.commit()
    return company


def _patched(*, is_follow_up: bool, answer=_ANSWER):
    fake_state = type("_State", (), {"values": {"grounding_set": {}}} if is_follow_up else {"values": {}})()
    return (
        patch("app.agent.cache.run_agent", return_value=answer),
        patch("app.agent.cache.COMPILED_GRAPH.get_state", return_value=fake_state),
    )


class TestGetCachedOrRunAgent:
    def test_first_call_runs_the_agent_and_writes_a_cache_row(self, db_session):
        _make_company(db_session)
        run_agent_patch, state_patch = _patched(is_follow_up=False)
        with run_agent_patch as mock_run_agent, state_patch:
            result = get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "why did it move?", "thread-1")

        mock_run_agent.assert_called_once()
        assert result == _ANSWER
        rows = db_session.query(AgentAnswerCache).all()
        assert len(rows) == 1
        assert rows[0].question == "why did it move?"
        assert rows[0].prompt_version == PROMPT_VERSION

    def test_second_identical_call_hits_the_cache_without_rerunning_the_agent(self, db_session):
        _make_company(db_session)
        run_agent_patch, state_patch = _patched(is_follow_up=False)
        with run_agent_patch as mock_run_agent, state_patch:
            get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "why did it move?", "thread-1")
            result = get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "why did it move?", "thread-2")

        mock_run_agent.assert_called_once()  # not called again on the second, cached call
        assert result == _ANSWER
        assert len(db_session.query(AgentAnswerCache).all()) == 1

    def test_a_different_question_is_a_cache_miss(self, db_session):
        _make_company(db_session)
        run_agent_patch, state_patch = _patched(is_follow_up=False)
        with run_agent_patch as mock_run_agent, state_patch:
            get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "why did it move?", "thread-1")
            get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "what caused the drop?", "thread-2")

        assert mock_run_agent.call_count == 2
        assert len(db_session.query(AgentAnswerCache).all()) == 2

    def test_follow_up_always_bypasses_the_cache(self, db_session):
        _make_company(db_session)
        run_agent_patch, state_patch = _patched(is_follow_up=True)
        with run_agent_patch as mock_run_agent, state_patch:
            get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "why did it move?", "thread-1")
            get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "why did it move?", "thread-1")

        assert mock_run_agent.call_count == 2  # never cached: no cache row written for follow-ups either
        assert len(db_session.query(AgentAnswerCache).all()) == 0

    def test_a_stale_prompt_version_is_not_matched(self, db_session):
        company = _make_company(db_session)
        db_session.add(
            AgentAnswerCache(
                company_cik=company.cik,
                investigation_date=datetime.date(2024, 3, 15),
                question="why did it move?",
                prompt_version=PROMPT_VERSION - 1,
                final_answer=_ANSWER.model_dump(mode="json"),
                created_at=datetime.datetime.now(tz=datetime.UTC),
            )
        )
        db_session.commit()

        run_agent_patch, state_patch = _patched(is_follow_up=False)
        with run_agent_patch as mock_run_agent, state_patch:
            get_cached_or_run_agent(db_session, "TEST", "2024-03-15", "why did it move?", "thread-1")

        mock_run_agent.assert_called_once()  # stale-version row ignored -> fresh run, not a hit
