# Company Financial Analyst (Earnings Timeline AI)

Company research site: search any public company, see side-by-side historical timelines of stock price vs. fundamentals (revenue, EBITDA, FCF, margins), and click any point on the chart to have a LangGraph agent explain the move — grounded in SEC filings (10-K/10-Q/8-K) and news, with citations.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design doc, and [`CLAUDE.md`](CLAUDE.md) for working conventions on this project.

## AI concepts demonstrated

RAG over SEC filings (structural chunking, quarter/date-scoped pgvector retrieval), LangGraph agent with expanding-window causal search, LLM-as-judge + programmatic eval harness, output validation/guardrails on structured agent responses.

## Status

Design phase — no code written yet. See `docs/DESIGN.md` §11 for the build plan.
