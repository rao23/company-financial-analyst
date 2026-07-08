"""Output guardrails (DESIGN.md §10).

Citation-existence check: every source_id the model cites must match a
chunk actually returned by some tool call earlier in the current
Investigation Thread (the Grounding Set, ADR-0006/0009) -- not just the
most recent tool call. If the model cites something never retrieved,
reject the answer rather than let a hallucinated citation through.
"""

from app.agent.schemas import SubmitFinalAnswer


class InsufficientGroundingError(Exception):
    """Raised when the model cites a source_id absent from the Grounding
    Set -- the caller should fall back to an "insufficient grounding"
    response rather than surface the answer as-is.
    """


def validate_citations(output: SubmitFinalAnswer, grounding_set: dict[str, dict]) -> None:
    if output.no_clear_cause:
        return  # no citations are expected to ground an honest "no cause found"

    ungrounded = [c.source_id for c in output.citations if c.source_id not in grounding_set]
    if ungrounded:
        raise InsufficientGroundingError(
            f"Cited source_id(s) not in this thread's Grounding Set: {ungrounded}"
        )
