"""LLM-as-judge eval metrics (DESIGN.md §9): Faithfulness and
Timing-awareness. These two are the deliberate exceptions to this
project's general preference for deterministic checks over judged ones
(ADR-0007, see metrics.py) -- "does this claim trace to this text" and
"is the reversal cause correctly attributed" aren't tasks a plain
comparison can do; they need actual model judgment.

These prompts are the highest-judgment, least-mechanical part of the
whole eval harness -- worth reviewing and iterating on once real eval
cases surface where the judge's calls feel wrong, rather than trusting
this first draft blindly.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

_JUDGE_MODEL = "gemini-2.5-flash"


class FaithfulnessJudgment(BaseModel):
    every_claim_grounded: bool = Field(
        description="True only if EVERY factual claim in the explanation is directly supported by the "
        "provided source chunks -- not just the overall gist or a plausible-sounding elaboration."
    )
    unsupported_claims: list[str] = Field(
        description="Specific claims the explanation makes that the source chunks do NOT support. "
        "Empty list if every_claim_grounded is True."
    )


_FAITHFULNESS_PROMPT = """You are checking whether an AI-generated explanation is fully grounded in its cited sources.

Investigation question: {question}

Explanation to check:
{explanation}

Source chunks the explanation was allowed to cite:
{source_chunks}

Check EVERY factual claim in the explanation against the source chunks above. A claim is grounded only \
if the source chunks actually state it (or something that directly implies it) -- not merely if it's \
plausible or generically true of the situation. Flag any claim, including implied causation, that the \
sources don't actually establish."""


def judge_faithfulness(
    question: str, explanation: str, source_chunks: list[str], llm: ChatGoogleGenerativeAI | None = None
) -> FaithfulnessJudgment:
    if llm is None:
        llm = ChatGoogleGenerativeAI(model=_JUDGE_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(FaithfulnessJudgment)
    prompt = _FAITHFULNESS_PROMPT.format(
        question=question,
        explanation=explanation,
        source_chunks="\n\n".join(f"[{i}] {chunk}" for i, chunk in enumerate(source_chunks)),
    )
    return structured_llm.invoke([("human", prompt)])


class TimingJudgment(BaseModel):
    lag_correct: bool = Field(
        description="True if the stated lag_days accurately reflects the real gap between the cited "
        "event's date and the Investigation Date, based on dates the explanation itself cites."
    )
    cause_correctly_attributed: bool = Field(
        description="For Trend cases: true if the explanation attributes the reversal to a cause near "
        "the actual Trend Start date, not to an earlier, unrelated event that merely falls inside the "
        "search window. Always true for Move cases (not applicable)."
    )
    reasoning: str = Field(description="Brief explanation of the judgment.")


_TIMING_PROMPT = """You are checking the timing-awareness of an AI-generated explanation for a stock price move.

Investigation Date: {investigation_date}
Query type: {query_type}
Trend Start (if this is a Trend case): {trend_start_date}

Explanation to check:
{explanation}

Stated lag (days between the cited event and the Investigation Date): {lag_days}

Check:
1. Is the stated lag_days consistent with the actual dates the explanation itself cites? (e.g. if it \
cites an event from 10 days before the Investigation Date, lag_days should be approximately 10, not 0 \
or some other unrelated number.)
2. {trend_instruction}"""

_TREND_INSTRUCTION = (
    "For this Trend case: does the explanation correctly attribute the reversal to a cause near the "
    "Trend Start date, rather than to an earlier, unrelated event that merely falls inside the search "
    "window?"
)
_MOVE_INSTRUCTION = "(Not applicable -- this is a Move case, not a Trend case. Set cause_correctly_attributed to true.)"


def judge_timing_awareness(
    investigation_date: str,
    query_type: str,
    explanation: str,
    lag_days: int | None,
    trend_start_date: str | None = None,
    llm: ChatGoogleGenerativeAI | None = None,
) -> TimingJudgment:
    if llm is None:
        llm = ChatGoogleGenerativeAI(model=_JUDGE_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(TimingJudgment)
    prompt = _TIMING_PROMPT.format(
        investigation_date=investigation_date,
        query_type=query_type,
        trend_start_date=trend_start_date or "N/A",
        explanation=explanation,
        lag_days=lag_days,
        trend_instruction=_TREND_INSTRUCTION if query_type == "trend" else _MOVE_INSTRUCTION,
    )
    return structured_llm.invoke([("human", prompt)])
