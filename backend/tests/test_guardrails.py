"""Tests for the citation-existence guardrail (app.agent.guardrails)."""

import pytest

from app.agent.guardrails import InsufficientGroundingError, validate_citations
from app.agent.schemas import Citation, SubmitFinalAnswer

GROUNDING_SET = {
    "filing:1": {"chunk_text": "grounded chunk"},
    "news:2": {"chunk_text": "another grounded chunk"},
}


def _output(citations, no_clear_cause=False):
    return SubmitFinalAnswer(
        explanation="explanation",
        citations=citations,
        lag_days=0 if not no_clear_cause else None,
        magnitude_match="strong",
        no_clear_cause=no_clear_cause,
    )


def test_passes_when_every_citation_is_grounded():
    output = _output([Citation(source_type="filing", source_id="filing:1", quote="q")])
    validate_citations(output, GROUNDING_SET)  # must not raise


def test_passes_when_citing_a_chunk_from_earlier_in_the_thread_not_just_the_latest_call():
    # The real case ADR-0006 exists for: a citation grounded by an earlier
    # tool call in the same thread, not the most recent one.
    output = _output([Citation(source_type="news", source_id="news:2", quote="q")])
    validate_citations(output, GROUNDING_SET)


def test_rejects_a_citation_never_actually_retrieved():
    output = _output([Citation(source_type="filing", source_id="filing:999", quote="q")])
    with pytest.raises(InsufficientGroundingError):
        validate_citations(output, GROUNDING_SET)


def test_no_clear_cause_skips_the_check_even_with_no_citations():
    output = _output([], no_clear_cause=True)
    validate_citations(output, {})  # must not raise despite an empty grounding set
