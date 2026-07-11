"""Tests for the /agent API (app.api.agent).

get_cached_or_run_agent is mocked -- its own behavior (caching, follow-up
bypass) is covered in test_agent_cache.py. This is just about the route's
own wiring: thread_id generation/passthrough and response shape.
"""

from unittest.mock import patch

from app.agent.schemas import Citation, FinalAnswer
from app.api.agent import AskRequest, ask

_ANSWER = FinalAnswer(
    explanation="A cause.",
    citations=[Citation(source_type="filing", source_id="filing:1", quote="quote")],
    lag_days=1,
    confidence=0.8,
    no_clear_cause=False,
)


def test_generates_a_thread_id_when_none_is_given(db_session):
    with patch("app.api.agent.get_cached_or_run_agent", return_value=_ANSWER) as mock_run:
        response = ask(AskRequest(ticker="AAPL", investigation_date="2024-03-15", question="why?"), db=db_session)

    assert response.thread_id  # non-empty, freshly generated
    mock_run.assert_called_once_with(db_session, "AAPL", "2024-03-15", "why?", response.thread_id)
    assert response.explanation == "A cause."


def test_passes_through_an_existing_thread_id_for_a_follow_up(db_session):
    with patch("app.api.agent.get_cached_or_run_agent", return_value=_ANSWER) as mock_run:
        response = ask(
            AskRequest(ticker="AAPL", investigation_date="2024-03-15", question="and then?", thread_id="thread-123"),
            db=db_session,
        )

    assert response.thread_id == "thread-123"
    mock_run.assert_called_once_with(db_session, "AAPL", "2024-03-15", "and then?", "thread-123")
