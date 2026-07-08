"""Derive `confidence` from a deterministic rubric, never LLM self-report
(ADR-0007). Inputs are exactly the signals the ADR names: which
expanding-window tier resolved the answer, the trust_level of the primary
citation, and the model's own magnitude-match assessment (a categorical
signal, not a raw self-reported confidence number -- see AgentOutput).

The exact weights below are a documented first pass, not empirically
tuned -- there's no labeled eval data to tune against until Phase 5 exists.
Revisit once real eval cases can validate whether these scores actually
track answer quality.
"""

from typing import Literal

from app.agent.schemas import MagnitudeMatch, SourceType

WindowTier = Literal[14, 90, 180]

_BASE_CONFIDENCE_BY_TIER: dict[WindowTier, float] = {
    # A cause found in the narrowest window is the strongest signal of a
    # direct, well-timed relationship; needing the widest window to find
    # anything at all is inherently a weaker correlation.
    14: 0.90,
    90: 0.70,
    180: 0.50,
}

_TRUST_LEVEL_ADJUSTMENT: dict[SourceType, float] = {
    "filing": 0.05,  # official, primary-source disclosure
    "news": -0.05,  # unofficial, secondary reporting
}

_MAGNITUDE_MATCH_ADJUSTMENT: dict[MagnitudeMatch, float] = {
    "strong": 0.05,
    "unclear": -0.05,
    "weak": -0.15,  # the cause plausibly doesn't explain a move this size -- penalize more than "unclear"
}


def derive_confidence(
    window_tier: WindowTier,
    primary_citation_source_type: SourceType,
    magnitude_match: MagnitudeMatch,
    no_clear_cause: bool,
) -> float | None:
    """Returns None when no_clear_cause is True: that's the separate
    Honesty-on-no-cause case (DESIGN.md §9), not the lowest confidence
    bucket -- conflating the two would penalize the agent for correctly
    declining to fabricate a cause.
    """
    if no_clear_cause:
        return None

    score = _BASE_CONFIDENCE_BY_TIER[window_tier]
    score += _TRUST_LEVEL_ADJUSTMENT[primary_citation_source_type]
    score += _MAGNITUDE_MATCH_ADJUSTMENT[magnitude_match]
    return max(0.0, min(1.0, score))
