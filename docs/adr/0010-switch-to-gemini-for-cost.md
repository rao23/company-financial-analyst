# Use Google Gemini instead of Claude as the project's LLM

The design was originally built around Claude (`langchain-anthropic`), chosen for its tool-use mechanics (ADR-0008 picked LangGraph partly because of how cleanly it maps onto Claude's tool-use loop). We're switching to Google Gemini (`langchain-google-genai`) for cost reasons — Gemini has a free tier, and this is a personal learning project where API spend is a real constraint.

This is a deliberate tradeoff, not a free substitution. The design leans hard on reliable tool-calling and structured output — the expanding-window agent makes up to three sequential tool calls before answering, the final answer must conform to a strict Pydantic schema, and the LLM-as-judge eval layer depends on consistent instruction-following. Free-tier and smaller models are historically less reliable at exactly these things than Claude, which makes it harder to isolate "is my prompt/tool-schema wrong" from "is the model just not following instructions" while debugging. We're accepting that risk for cost reasons; if tool-calling reliability becomes a recurring blocker during Phase 4, revisit this decision rather than working around it indefinitely.

LangGraph itself is unaffected — it's model-agnostic orchestration (§8) and only the model client changes, not the graph structure.
