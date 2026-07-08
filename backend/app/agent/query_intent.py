"""Query Intent classification (DESIGN.md §8, ADR-0003, CONTEXT.md "Query
Intent").

A single free-text input sits next to the chart -- the user never picks a
mode explicitly. This node infers, from wording alone, whether the
question is a **Move** query ("why did it drop here" -- a single-point
price move) or a **Trend** query ("why is it trending down" -- a
directional multi-day movement), before any retrieval tool runs. On
genuinely ambiguous wording (e.g. "what happened here?"), it defaults to
Trend rather than Move, and rather than asking a clarifying question.

Deliberately an LLM call, not a keyword heuristic (ADR-0003) -- wording
like "why is this happening" carries no reliable lexical signal for
Move vs Trend, but a model reasoning about the phrasing can classify it
the way a human reading the question would.
"""

from typing import Literal

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

QueryIntent = Literal["move", "trend"]

_SYSTEM_PROMPT = """You classify a user's question about a stock chart into one of two intents.

- "move": the question asks about a single-point price move at the Investigation Date.
  Example: "why did it drop here", "what caused the spike on this day", "why did the stock fall today"
- "trend": the question asks about a directional movement over multiple days leading up to
  the Investigation Date.
  Example: "why is it trending down", "why has it been declining", "what's driving the rally
  this month"

If the wording is genuinely ambiguous and doesn't clearly indicate either a single-day move
or a multi-day trend, classify it as "trend" -- do not guess "move" as a default, and do not
ask a clarifying question. Examples of ambiguous wording that should default to "trend":
"what happened here?", "why did this happen?", "explain this."

Respond with your classification of the user's question."""


class QueryIntentClassification(BaseModel):
    intent: QueryIntent = Field(description='Either "move" or "trend".')


def classify_query_intent(question: str, llm: ChatGoogleGenerativeAI | None = None) -> QueryIntent:
    """Classify a user's free-text question as a Move or Trend query.

    `llm` is injectable for testing (pass a fake/mock); defaults to a
    temperature=0 Gemini call for real use, since classification should be
    deterministic, not creative.
    """
    if llm is None:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    structured_llm = llm.with_structured_output(QueryIntentClassification)
    result = structured_llm.invoke(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", question),
        ]
    )
    return result.intent
