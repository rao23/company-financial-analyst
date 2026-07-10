"""The LangGraph agent (DESIGN.md §8): classifies Query Intent, then runs
a tool-use loop with a deterministic expanding-window retry and a
Grounding-Set-checked structured final answer.

Orchestration overview:
    START -> classify_intent -> agent <-> execute_tools -> [end | force_end | widen_window -> agent]

- `agent` is bound to the 5 data tools plus SubmitFinalAnswer, with
  tool_choice="any" -- the model always calls something, so there's no
  "did it forget to call a tool" branch to handle.
- `execute_tools` runs every tool call from the latest turn, folds any
  filing/news chunks into the thread-wide Grounding Set (ADR-0006/0009),
  and intercepts SubmitFinalAnswer calls: validates citations against the
  Grounding Set, derives confidence (ADR-0007), and stores the result.
- The conditional edge after `execute_tools` is where the *deterministic*
  force-widen lives (grounding empty after a retrieval call -> widen,
  never left to the model's discretion, per TASKS.md). The *LLM-judged*
  widen (magnitude doesn't match) needs no special graph machinery: the
  system prompt instructs the model to call the retrieval tools again
  with a wider date range itself, which it can already do since date
  ranges are ordinary tool arguments.
"""

import datetime
import json
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent import tools as agent_tools
from app.agent.confidence import derive_confidence
from app.agent.guardrails import InsufficientGroundingError, validate_citations
from app.agent.prompts import build_system_prompt, wrap_untrusted_text
from app.agent.query_intent import classify_query_intent
from app.agent.schemas import FinalAnswer, SubmitFinalAnswer
from app.db import SessionLocal

MODEL = "gemini-2.5-flash"
MAX_ROUNDS = 8
_NEXT_WINDOW_DAYS = {14: 90, 90: 180}


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    ticker: str
    investigation_date: str
    question: str
    query_intent: str
    window_days: int
    grounding_set: dict[str, dict]
    rounds: int
    retrieval_calls_this_round: int
    new_chunks_this_round: int
    final_answer: dict | None


def _run_tool(fn, **kwargs) -> dict | list[dict]:
    """Opens a session per call and converts the tools' input-validation
    ValueErrors (bad ticker, bad quarter format) into an error dict the
    model can react to -- an uncaught exception here would crash the
    whole graph over what's often just a malformed tool call.
    """
    db = SessionLocal()
    try:
        return fn(db, **kwargs)
    except ValueError as e:
        return {"error": str(e)}
    finally:
        db.close()


@tool
def get_financials_tool(ticker: str, quarter: str) -> dict:
    """Get revenue, EPS, EBITDA, and free cash flow for a company's fiscal
    quarter (e.g. "2024Q1") or fiscal year (e.g. "2024FY")."""
    return _run_tool(agent_tools.get_financials, ticker=ticker, quarter=quarter)


@tool
def get_filing_chunks_tool(ticker: str, date_from: str, date_to: str, query: str, top_k: int = 5) -> list[dict]:
    """Search SEC filing text (10-K/10-Q/8-K) for a company within a date range (ISO dates,
    YYYY-MM-DD), ranked by relevance to `query`. Official, primary-source disclosures."""
    return _run_tool(
        agent_tools.get_filing_chunks,
        ticker=ticker,
        date_from=datetime.date.fromisoformat(date_from),
        date_to=datetime.date.fromisoformat(date_to),
        query=query,
        top_k=top_k,
    )


@tool
def get_news_tool(ticker: str, date_from: str, date_to: str) -> list[dict]:
    """Get news articles for a company within a date range (ISO dates, YYYY-MM-DD),
    chronological. Unofficial, secondary-source reporting -- covers things
    that never appear in a filing (analyst actions, competitor moves, litigation)."""
    return _run_tool(
        agent_tools.get_news,
        ticker=ticker,
        date_from=datetime.date.fromisoformat(date_from),
        date_to=datetime.date.fromisoformat(date_to),
    )


@tool
def get_price_context_tool(ticker: str, date: str) -> dict:
    """For a single-day Move: get the price change on `date` (ISO date) against a
    smoothed trailing-5-day-average baseline. Use this to judge whether a found
    cause is big enough to explain the move's actual size."""
    return _run_tool(agent_tools.get_price_context, ticker=ticker, date=datetime.date.fromisoformat(date))


@tool
def get_price_trend_tool(ticker: str, date: str) -> dict:
    """For a directional Trend: walk backward from `date` (ISO date) to find the Trend
    Start -- the swing point (local peak/trough) where the current run began.
    Returns {direction, trend_start_date, cumulative_move_pct}."""
    return _run_tool(agent_tools.get_price_trend, ticker=ticker, date=datetime.date.fromisoformat(date))


DATA_TOOLS = [
    get_financials_tool,
    get_filing_chunks_tool,
    get_news_tool,
    get_price_context_tool,
    get_price_trend_tool,
]
_TOOL_DISPATCH = {t.name: t for t in DATA_TOOLS}


def classify_intent_node(state: AgentState) -> dict:
    return {"query_intent": classify_query_intent(state["question"])}


def agent_node(state: AgentState) -> dict:
    llm = ChatGoogleGenerativeAI(model=MODEL, temperature=0)
    llm_with_tools = llm.bind_tools([*DATA_TOOLS, SubmitFinalAnswer], tool_choice="any")

    system_message = SystemMessage(
        build_system_prompt(state["ticker"], state["investigation_date"], state["query_intent"])
    )
    response = llm_with_tools.invoke([system_message, *state["messages"]])
    return {"messages": [response]}


def execute_tools_node(state: AgentState) -> dict:
    tool_calls = state["messages"][-1].tool_calls

    response_messages = []
    grounding_set = dict(state["grounding_set"])
    retrieval_calls = 0
    new_chunks = 0
    final_answer = None

    for call in tool_calls:
        if call["name"] == "SubmitFinalAnswer":
            output = SubmitFinalAnswer.model_validate(call["args"])
            try:
                validate_citations(output, grounding_set)
            except InsufficientGroundingError as e:
                response_messages.append(
                    ToolMessage(
                        content=f"Rejected: {e} Only cite source_ids you actually retrieved via a tool call.",
                        tool_call_id=call["id"],
                        name=call["name"],
                    )
                )
                continue

            primary_source_type = output.citations[0].source_type if output.citations else "news"
            confidence = derive_confidence(
                window_tier=state["window_days"],
                primary_citation_source_type=primary_source_type,
                magnitude_match=output.magnitude_match,
                no_clear_cause=output.no_clear_cause,
            )
            final_answer = FinalAnswer(
                explanation=output.explanation,
                citations=output.citations,
                lag_days=output.lag_days,
                confidence=confidence,
                no_clear_cause=output.no_clear_cause,
            ).model_dump(mode="json")
            response_messages.append(
                ToolMessage(content="Final answer recorded.", tool_call_id=call["id"], name=call["name"])
            )
            continue

        tool_fn = _TOOL_DISPATCH.get(call["name"])
        if tool_fn is None:
            response_messages.append(
                ToolMessage(content=f"Unknown tool: {call['name']}", tool_call_id=call["id"], name=call["name"])
            )
            continue

        result = tool_fn.invoke(call["args"])
        serialized_result = result
        if isinstance(result, list):
            retrieval_calls += 1
            for chunk in result:
                key = f"{chunk['source_type']}:{chunk['chunk_id']}"
                if key not in grounding_set:
                    grounding_set[key] = chunk
                    new_chunks += 1
            # Delimit only for what the model sees -- the Grounding Set above
            # keeps raw chunk_text, since citations/eval scoring need the
            # actual source text, not the wrapped copy.
            serialized_result = [
                {**chunk, "chunk_text": wrap_untrusted_text(chunk["chunk_text"])} for chunk in result
            ]

        response_messages.append(
            ToolMessage(content=json.dumps(serialized_result, default=str), tool_call_id=call["id"], name=call["name"])
        )

    return {
        "messages": response_messages,
        "grounding_set": grounding_set,
        "retrieval_calls_this_round": retrieval_calls,
        "new_chunks_this_round": new_chunks,
        "rounds": state["rounds"] + 1,
        "final_answer": final_answer,
    }


def widen_window_node(state: AgentState) -> dict:
    new_window = _NEXT_WINDOW_DAYS[state["window_days"]]
    notice = HumanMessage(
        content=(
            f"No new results were found in the {state['window_days']}-day window. The search window "
            f"has been automatically widened to {new_window} days -- retry your retrieval tool calls "
            "(get_filing_chunks_tool / get_news_tool) with a date_from that far back from the "
            "Investigation Date before answering."
        )
    )
    return {"window_days": new_window, "messages": [notice]}


def force_end_node(state: AgentState) -> dict:
    final_answer = FinalAnswer(
        explanation="Reached the maximum number of tool-call rounds without a fully grounded answer.",
        citations=[],
        lag_days=None,
        confidence=None,
        no_clear_cause=True,
    ).model_dump(mode="json")
    return {"final_answer": final_answer}


def route_after_tools(state: AgentState) -> str:
    if state.get("final_answer") is not None:
        return "end"
    if state["rounds"] >= MAX_ROUNDS:
        return "force_end"
    if state["retrieval_calls_this_round"] > 0 and state["new_chunks_this_round"] == 0 and state["window_days"] < 180:
        return "widen_window"
    return "agent"


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("agent", agent_node)
    graph.add_node("execute_tools", execute_tools_node)
    graph.add_node("widen_window", widen_window_node)
    graph.add_node("force_end", force_end_node)

    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "agent")
    graph.add_edge("agent", "execute_tools")
    graph.add_conditional_edges(
        "execute_tools",
        route_after_tools,
        {"end": END, "force_end": "force_end", "widen_window": "widen_window", "agent": "agent"},
    )
    graph.add_edge("widen_window", "agent")
    graph.add_edge("force_end", END)

    # In-memory only -- lost on process restart. Fine for now (no deployed
    # persistence layer exists yet); swap for a real checkpointer (e.g.
    # Postgres-backed) before this needs to survive a restart.
    return graph.compile(checkpointer=MemorySaver())


COMPILED_GRAPH = _build_graph()


def run_agent(ticker: str, investigation_date: str, question: str, thread_id: str) -> FinalAnswer:
    """`thread_id` scopes the Investigation Thread (ADR-0009): reuse the
    same thread_id for a follow-up question about the same Investigation
    Date -- prior messages and the Grounding Set carry over. Use a new
    thread_id when the user clicks a new point on the chart.
    """
    config = {"configurable": {"thread_id": thread_id}}
    is_follow_up = bool(COMPILED_GRAPH.get_state(config).values)

    input_state: dict = {
        "messages": [HumanMessage(question)],
        "question": question,
        "window_days": 14,
        "rounds": 0,
        "retrieval_calls_this_round": 0,
        "new_chunks_this_round": 0,
        "final_answer": None,
    }
    if not is_follow_up:
        input_state.update(
            ticker=ticker,
            investigation_date=investigation_date,
            query_intent="trend",  # placeholder; overwritten by classify_intent_node before first use
            grounding_set={},
        )

    result_state = COMPILED_GRAPH.invoke(input_state, config=config)
    return FinalAnswer.model_validate(result_state["final_answer"])
