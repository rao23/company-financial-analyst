"""Structured agent output (DESIGN.md §10): the final answer is
constrained to this schema, not free text.
"""

from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["filing", "news"]
MagnitudeMatch = Literal["strong", "weak", "unclear"]


class Citation(BaseModel):
    source_type: SourceType
    source_id: str = Field(description='Grounding Set key, e.g. "filing:123" or "news:45".')
    quote: str = Field(description="The specific quoted text from that chunk supporting the claim.")


class SubmitFinalAnswer(BaseModel):
    """Call this when you have your final answer, instead of replying in
    plain text. Every claim must be grounded in a chunk you actually
    retrieved via the other tools.

    (Dev note: this docstring is also the tool description the model sees
    -- bound directly as a tool in app/agent/graph.py, where the class
    name is literally the tool name the model calls. `confidence` is
    deliberately NOT a field here: it's derived afterward by
    app.agent.confidence.derive_confidence from these signals plus graph
    state (ADR-0007), never self-reported by the model.)
    """

    explanation: str = Field(description="The explanation, citing sources and stating lag if not same-day.")
    citations: list[Citation]
    lag_days: int | None = Field(description="Days between the cited event and the Investigation Date. None only if no_clear_cause is true.")
    magnitude_match: MagnitudeMatch = Field(
        description=(
            "Does the cited cause's apparent significance match the price move's actual magnitude "
            "(from get_price_context/get_price_trend)? 'strong' if it clearly does, 'weak' if the cause "
            "seems too minor to explain the move, 'unclear' if magnitude can't be assessed."
        )
    )
    no_clear_cause: bool = Field(
        description="True if no discoverable single triggering event was found even at the widest search window. Do not fabricate a cause to avoid setting this true."
    )


class FinalAnswer(BaseModel):
    """The validated response returned to the caller: AgentOutput plus the
    derived confidence score, after the citation-existence guardrail
    (app.agent.guardrails) has passed.
    """

    explanation: str
    citations: list[Citation]
    lag_days: int | None
    confidence: float | None = Field(description="None when no_clear_cause is true -- confidence doesn't apply to that case (ADR-0007).")
    no_clear_cause: bool
