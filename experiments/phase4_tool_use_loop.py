"""
Phase 4 — raw tool-use loop, hand-rolled (see docs/TASKS.md, DESIGN.md §8).

Throwaway exercise, not part of the app. Goal: see the function-calling
mechanism directly against the google-genai SDK -- model returns a
function_call part, you execute it, you send back a function_response,
repeat -- before LangGraph abstracts this into nodes/edges for the real
agent.

The tool below is intentionally synthetic (hardcoded data, not a real DB
query) so the exercise stays focused on the loop mechanics, not plumbing.

Run:
    pip install -r experiments/requirements.txt
    cp experiments/.env.example experiments/.env   # fill in your Gemini API key
    python experiments/phase4_tool_use_loop.py
"""

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL = "gemini-2.5-flash"

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MAX_TOOL_CALL_ROUNDS = 5  # hard cap -- a buggy loop should error, not spin forever


# --- The "tool" itself: plain Python, no agent framework involved yet. ---
# Hardcoded so the exercise doesn't depend on the real price_history table.
_FAKE_PRICES = {
    ("AAPL", "2024-01-15"): 185.14,
    ("AAPL", "2024-06-10"): 193.12,
}


def get_stock_price(ticker: str, date: str) -> dict:
    """The actual Python function the model's tool call will invoke.
    Returns a dict, not a string -- the SDK serializes it into the
    function_response part for you.
    """
    price = _FAKE_PRICES.get((ticker.upper(), date))
    if price is None:
        return {"error": f"no price on file for {ticker} on {date}"}
    return {"ticker": ticker.upper(), "date": date, "close": price}


# The schema Gemini uses to decide whether/how to call get_stock_price.
# `description` is what the model reasons over to decide relevance -- vague
# descriptions produce wrong or missed tool calls, so it's worth being this
# explicit even for a two-argument function.
get_stock_price_declaration = types.FunctionDeclaration(
    name="get_stock_price",
    description=(
        "Get the closing stock price for a given ticker on a given date. "
        "Use this whenever the user asks about a stock's price on a specific date."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "ticker": types.Schema(type=types.Type.STRING, description="Stock ticker symbol, e.g. AAPL"),
            "date": types.Schema(type=types.Type.STRING, description="Date in YYYY-MM-DD format"),
        },
        required=["ticker", "date"],
    ),
)
tools = types.Tool(function_declarations=[get_stock_price_declaration])

# Dispatch table: function name (as the model will refer to it) -> the
# actual Python callable to invoke.
AVAILABLE_TOOLS = {"get_stock_price": get_stock_price}


def run_tool_use_loop(user_prompt: str) -> str:
    """Send user_prompt to Gemini, executing any tool calls it requests
    until it returns a plain-text answer (or MAX_TOOL_CALL_ROUNDS is hit).
    """
    contents = [types.Content(role="user", parts=[types.Part(text=user_prompt)])]

    for round_number in range(MAX_TOOL_CALL_ROUNDS):
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(tools=[tools]),
        )
        candidate_content = response.candidates[0].content
        function_calls = [part.function_call for part in candidate_content.parts if part.function_call]

        if not function_calls:
            return response.text

        print(f"  [round {round_number}] model requested {len(function_calls)} tool call(s)")

        # The model's own function-call turn has to be replayed back to it
        # alongside our function_response parts -- otherwise it loses track
        # of what it asked for and why.
        contents.append(candidate_content)

        response_parts = []
        for call in function_calls:
            tool_fn = AVAILABLE_TOOLS.get(call.name)
            if tool_fn is None:
                result = {"error": f"no such tool: {call.name}"}
            else:
                print(f"    -> calling {call.name}({dict(call.args)})")
                result = tool_fn(**call.args)
            response_parts.append(types.Part.from_function_response(name=call.name, response=result))

        contents.append(types.Content(role="user", parts=response_parts))

    raise RuntimeError(f"Exceeded {MAX_TOOL_CALL_ROUNDS} tool-call rounds without a final answer")


if __name__ == "__main__":
    print(run_tool_use_loop("What was AAPL's closing price on 2024-01-15?"))
