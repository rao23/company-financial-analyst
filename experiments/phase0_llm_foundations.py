"""
Phase 0 — LLM foundations (see docs/TASKS.md).

Throwaway exploration script, not part of the app. Goal: build hands-on
intuition for temperature and context-window behavior before any framework
(LangGraph, retrieval, etc.) sits between you and the raw API.

Run:
    pip install -r experiments/requirements.txt
    cp experiments/.env.example experiments/.env   # fill in your Gemini API key
    python experiments/phase0_llm_foundations.py
"""

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

MODEL = "gemini-2.5-flash"  # cheap/fast is fine for this experiment; check
# https://ai.google.dev/gemini-api/docs/models for current model names

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def call_gemini(prompt: str, temperature: float, max_output_tokens: int = 300) -> str:
    """Send one prompt, print token usage, return the text response.

    Raises whatever the SDK raises (e.g. google.genai.errors.APIError) on
    failure — deliberately not caught here, since seeing the raw
    exception is the point for the context-window experiment below.
    """
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    usage = response.usage_metadata
    finish_reason = response.candidates[0].finish_reason if response.candidates else None
    print(
        f"  [temperature={temperature}] "
        f"in={usage.prompt_token_count} out={usage.candidates_token_count} tokens "
        f"finish_reason={finish_reason}"
    )
    print(f"  -> {response.text!r}")
    return response.text


def temperature_experiment() -> None:
    """Run the same prompt multiple times at temperature=0 vs temperature=1.

    TODO(you): pick a prompt where sampling variance would actually be
    visible. Not every prompt qualifies — a purely factual, single-answer
    prompt ("what is 2+2?") won't show variance at any temperature, and
    noticing *why* that is is itself part of the exercise. Try a few
    different kinds of prompts (open-ended vs. factual) and compare.

    Run each prompt 3+ times per temperature so you're comparing across
    runs, not just eyeballing one sample.
    """
    prompt = "According to you, who do you think the ballon d'or winner will be for this year?"  # TODO: fill in

    if not prompt:
        print("temperature_experiment: fill in `prompt` above, then re-run.")
        return

    for temperature in (0.0, 1.0):
        print(f"\n--- temperature={temperature} ---")
        for _ in range(3):
            call_gemini(prompt, temperature=temperature)


def context_window_experiment() -> None:
    """Deliberately exceed a token budget and observe what actually happens.

    Two different limits, tested separately (with a pause between, so the
    second call doesn't restack on the free tier's ~5 RPM cap) — they fail
    differently:
      1. Exceed `max_output_tokens` (the output budget) with a prompt that
         invites a long response. Watch `finish_reason` above, not just
         the text — on thinking-enabled models, MAX_TOKENS can come back
         with empty `response.text` rather than a truncated string.
      2. Exceed the model's total context window by constructing a very
         large `prompt` (input side). TODO(you): fill this one in —
         repeating a string many times is a quick way to pad tokens
         without needing real text.
    """
    long_output_prompt = "write a detailed 10000+ word essay on 10 stocks worth investing in today which accoridng to you would give the max returns in 10 years time. give detaield reasoning."

    print("--- scenario 1: exceed max_output_tokens ---")
    try:
        call_gemini(long_output_prompt, temperature=0.0)
    except errors.APIError as e:
        print(f"  Got {type(e).__name__} (code={e.code}): {e.message}")

    huge_input_prompt = "banana " * 1500000

    if not huge_input_prompt:
        print("\ncontext_window_experiment: fill in `huge_input_prompt` above, then re-run scenario 2.")
        return

    print("\nwaiting 15s to stay under the free-tier rate limit...")
    time.sleep(15)

    print("--- scenario 2: exceed total context window ---")
    try:
        call_gemini(huge_input_prompt, temperature=0.0)
    except errors.APIError as e:
        print(f"  Got {type(e).__name__} (code={e.code}): {e.message}")


if __name__ == "__main__":
    # print("=== Temperature experiment "
    # "===")
    # temperature_experiment()

    print("\n=== Context window experiment ===")
    context_window_experiment()
