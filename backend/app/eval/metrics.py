"""Programmatic (non-LLM-judge) eval metrics (DESIGN.md §9): Retrieval
Recall, Numeric Consistency, Trend Start Accuracy, Honesty-on-no-cause.
Faithfulness and Timing-awareness need actual model judgment and live in
judges.py instead -- these four don't, so they stay deterministic rather
than paying for (and trusting) an LLM call, consistent with this
project's general preference for programmatic checks over judged ones
wherever a plain comparison actually suffices (ADR-0007).
"""

import datetime
import re

NUMBER_PATTERN = re.compile(r"\$?(\d[\d,]*\.?\d*)\s*(billion|million|bn|mm|B|M)?", re.IGNORECASE)
_SCALE = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6}


def retrieval_recall(expected_source_ref: str, grounding_set: dict[str, dict]) -> bool:
    """True if a chunk whose source_url contains expected_source_ref is
    anywhere in the Grounding Set -- i.e. the agent actually retrieved the
    real documented source at some point in the thread, across every tool
    call and expanding-window retry, not just the most recent one.

    expected_source_ref should be entered as a full source URL or a
    distinctive substring of one (e.g. an accession number with dashes
    removed, matching how it appears in a SEC filing's source_url).
    """
    return any(expected_source_ref in chunk.get("source_url", "") for chunk in grounding_set.values())


def _extract_numbers(text: str) -> list[float]:
    """Heuristic, not exact: prose number extraction can misparse dates,
    share counts, or percentages as dollar figures. Good enough to catch
    an outright wrong number, not a substitute for careful human review
    of what this metric is actually flagging.
    """
    numbers = []
    for raw, suffix in NUMBER_PATTERN.findall(text):
        if not raw:
            continue
        value = float(raw.replace(",", ""))
        value *= _SCALE.get(suffix.lower(), 1)
        numbers.append(value)
    return numbers


def numeric_consistency(explanation: str, known_values: list[float], relative_tolerance: float = 0.02) -> bool:
    """True if every number cited in the explanation matches at least one
    real value from financial_metrics within `relative_tolerance` -- or if
    no numbers were cited at all (this metric catches contradiction, it
    doesn't require numbers to be cited in the first place).
    """
    cited = _extract_numbers(explanation)
    if not cited:
        return True
    return all(
        any(abs(value - known) / max(abs(known), 1.0) <= relative_tolerance for known in known_values)
        for value in cited
    )


def trend_start_accuracy(
    computed_trend_start: datetime.date, expected_min: datetime.date, expected_max: datetime.date
) -> bool:
    """A plain interval check (ADR-0004) -- not LLM-judged, since
    swing-point detection is threshold-tuned and an exact-date match would
    be brittle to any minor threshold change.
    """
    return expected_min <= computed_trend_start <= expected_max


def honesty_on_no_cause(expected_cause_type: str, agent_no_clear_cause: bool) -> bool:
    """True if the agent's no_clear_cause flag matches whether this case is
    actually labeled as having no discoverable cause -- catches both
    directions of failure: fabricating a cause when there isn't one, and
    giving up when a real cause was findable.
    """
    expected_no_cause = expected_cause_type == "no_clear_cause"
    return agent_no_clear_cause == expected_no_cause
