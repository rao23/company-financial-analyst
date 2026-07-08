# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read this file in full, along with `docs/DESIGN.md`, before doing anything else.

## Who you're working with

Software engineer at Google Cloud (Data & Analytics), 3-4 years experience, transitioning into AI Engineering roles outside Google. Strong in Python, data structures/algorithms, API design, git, GCP, Linux, and SWE fundamentals (testing, monitoring, logging). New to: Docker (comfortable picking it up progressively), LLMs/RAG/agents/evals (primary focus area, wants real hands-on depth, not just theory).

## How to work on this project

- **Applied AI topics** (prompt engineering, RAG, agent logic, eval harnesses): scaffold and structure only — imports, helpers, function signatures. The core logic (prompts, retrieval queries, tool definitions, agent nodes, eval scoring) gets written by the human, not generated wholesale. Review and iterate on it once written, don't pre-write it.
- **Foundational/mechanical topics** (SQLAlchemy models, Docker Compose config, boilerplate FastAPI routing): full working code is fine — this isn't where the learning value is.
- **Always lead with a brief concept explanation before writing any code for a new piece of the system** — what it is, why it's needed here, how it fits the design doc. Keep it tight, not a lecture.
- Don't over-explain Python basics or general SWE patterns — assume strong general engineering background.
- Flag prerequisite gaps explicitly rather than assuming something is already understood.
- Don't generate placeholder/stub code — everything should be functional and runnable, or clearly marked as a TODO for the human to fill in (for applied-AI core logic specifically).
- Be dense and direct in explanations, not exhaustive.

## Project standards

- README, `requirements.txt` (pinned), clear module structure, `.gitignore` — self-contained and cloneable.
- Every meaningful change to prompts, retrieval logic, or the agent should be checked against the eval harness (`docs/DESIGN.md` §9) before being treated as an improvement — this is a merge-gate discipline, not optional.
- Every phase ships with `backend/tests/` coverage for its deterministic logic (ingestion parsing/filtering, derivation math, chunking, retrieval filters) before being marked complete in `docs/TASKS.md` — not just manual verification against real data. Tests run against a dedicated `earnings_timeline_test` Postgres database (see `backend/tests/conftest.py`), never the dev DB. This is separate from the eval harness above, which judges agent/prompt/retrieval *quality*, not code correctness.
- This project is meant to be pushed to GitHub with a clean README — flag it if that hasn't happened yet once there's real code.

## Project: Earnings Timeline AI

Full design is in `docs/DESIGN.md` — goal, architecture, data sources, data model, agent design (LangGraph), eval harness, output validation/guardrails, and the phased build plan (§11). Read it before proposing any implementation.

One-line summary: a company research site — search a ticker, see fundamentals (revenue, EBITDA, FCF) plotted alongside stock price since IPO/XBRL coverage, click any point on the chart and a LangGraph agent explains the move, grounded in SEC filings (10-K/10-Q/8-K) and Finnhub news, with citations and an eval harness checking faithfulness/timing-awareness/honesty.

**Status: Phase 0 in progress** (`experiments/phase0_llm_foundations.py`). See the build plan in `docs/TASKS.md` and `docs/DESIGN.md` §11.

## Architecture snapshot

Stack: Postgres + pgvector · FastAPI · Next.js · LangGraph (`langchain-google-genai`, Google Gemini — ADR-0010) · `sentence-transformers` (local embeddings, no API cost) · Docker Compose.

```
backend/app/
  ingestion/   — SEC bulk loader, 8-K fetcher, Finnhub client, yfinance
  derivation/  — EBITDA/FCF computation from raw XBRL facts
  rag/         — chunking, embedding, pgvector retrieval (always metadata-filtered before ANN)
  agent/       — LangGraph graph + nodes, tool defs, output validation (Pydantic schema)
  eval/        — offline harness, online sampling hooks
  api/         — FastAPI routers
frontend/app/  — search, timeline charts (price + fundamentals overlay), click-to-ask panel
```

Key design invariants to keep in mind:
- Every chunk table carries `source_type` + `trust_level` (`filing`/`official` vs. `news`/`unofficial`) — used in retrieval filtering and agent prompt weighting.
- Retrieval is always company + date-range filtered first, then ANN — never a global vector search.
- EBITDA/FCF are derived (not XBRL-tagged), always from as-filed figures, never restated ones.
- The agent uses an expanding-window retry (14 → 90 → 180 days) before answering; must state lag explicitly and is allowed to say "no clear cause found."
- Agent output is a structured Pydantic schema (`explanation`, `citations`, `lag_days`, `confidence`) — not free text. Every cited `source_id` must match a chunk actually returned that turn.
- Eval harness is a merge gate — run it on every prompt/retrieval/model change before calling it an improvement.

## Commands (once scaffolded)

```bash
docker compose up -d          # start Postgres + pgvector
docker compose down -v        # tear down + wipe volumes

# backend (from backend/)
pip install -r requirements.txt
uvicorn app.main:app --reload

# run eval harness
python -m pytest backend/tests/ -v
python -m app.eval.offline    # full offline suite

# frontend (from frontend/)
npm install
npm run dev
```

_Commands are placeholders until the scaffold exists — update this section when they're wired up._

## Sibling project

A related project, Stock Insight AI, exists in a separate repo (`AI Course/stock-insight-ai` on the user's machine) and is on hold in favor of this one — same core stack (Postgres+pgvector, FastAPI, Next.js), but includes YouTube-based creator scoring that made it slower to ship. Some design patterns here (source_type/trust_level tagging, claim-checker-style grounding) were carried over from it.
