# Company Financial Analyst (Earnings Timeline AI)

Company research site: search any public company, see side-by-side historical timelines of stock price vs. fundamentals (revenue, EBITDA, FCF, margins), and click any point on the chart to have a LangGraph agent explain the move — grounded in SEC filings (10-K/10-Q/8-K) and news, with citations.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design doc, [`docs/TASKS.md`](docs/TASKS.md) for the phased build plan, [`CONTEXT.md`](CONTEXT.md) for the domain glossary, and [`docs/adr/`](docs/adr/) for architecture decisions.

## AI concepts demonstrated

RAG over SEC filings (structural chunking, quarter/date-scoped pgvector retrieval), LangGraph agent with expanding-window causal search, LLM-as-judge + programmatic eval harness, output validation/guardrails on structured agent responses.

## Status

Backend, including the LangGraph agent, complete through Phase 4. See `docs/TASKS.md` for the full checklist.

- **Phase 0** — Gemini API foundations (`experiments/phase0_llm_foundations.py`)
- **Phase 1** — Company/ticker ingestion, XBRL financial metrics, EBITDA/FCF derivation, price history, Pre-2009 Coverage Gap flag
- **Phase 2** — Filing fetch + Item-heading chunking, local embedding pipeline (pgvector), metadata-filtered retrieval
- **Phase 3** — 8-K ingestion, Finnhub news client + window-dedup, `news_articles`/`news_chunks` schema
- **Phase 4** — LangGraph agent: Query Intent classification, 5 data tools, expanding-window retry (14/90/180 days), Grounding Set, Investigation Thread/follow-ups, structured output with derived confidence and a citation-existence guardrail
- **Phase 5+** (next) — Eval harness, guardrail hardening, frontend — not started

Tests cover the deterministic logic across Phase 1–4 (ingestion, derivation, chunking, embedding, retrieval, the agent's tools/confidence rubric/guardrails, and the graph's control flow) — see `backend/tests/`. Every phase ships with test coverage before being marked complete. The agent's LLM calls (Query Intent, the tool-use loop) are additionally verified live against the real Gemini API — see `docs/TASKS.md` Phase 4 for specifics.

Requires free API keys for Finnhub (Phase 3 news) and Gemini (Phase 0 experiments, Phase 4 agent) in the root `.env` — `FINNHUB_API_KEY` and `GEMINI_API_KEY`. Note: Gemini's free tier caps `gemini-2.5-flash` at 20 requests/day per project, separate from its per-minute limit — the agent's tool-use loop can burn through this quickly during development (each turn is several model calls).

## Setup

Prerequisites: Python 3.13, Docker Desktop.

```bash
# 1. Start Postgres + pgvector
docker compose up -d

# 2. Configure environment
cp .env.example .env   # fill in POSTGRES_* and DATABASE_URL

# 3. Install backend dependencies
cd backend
pip install -r requirements.txt

# 4. Create tables (+ pgvector extension)
python -m app.init_db
```

## Running ingestion (in order)

```bash
# Phase 1 — companies, financials, prices
python -m app.ingestion.sec_companies                      # load company/ticker list
python -m app.ingestion.sec_financials <path-to-quarterly-zip>   # SEC Financial Statement Data Set
python -m app.derivation.ebitda_fcf                         # derive EBITDA/FCF from filed components
python -m app.ingestion.price_history <TICKER>               # e.g. AAPL

# Phase 2 — filings, chunking, embeddings
python -m app.ingestion.sec_filings <CIK> <ACCESSION_NUMBER>  # e.g. 320193 0000320193-24-000006
python -m app.rag.embed_chunks                                # embed any filing_chunks/news_chunks missing a vector

# Phase 3 — 8-Ks, news
python -m app.ingestion.sec_8k <CIK>                           # ingest every 8-K on file for a company
python -m app.ingestion.finnhub_news <TICKER> <FROM:YYYY-MM-DD> <TO:YYYY-MM-DD>
```

## Running the agent

```python
from app.agent.graph import run_agent

answer = run_agent(
    ticker="AAPL",
    investigation_date="2026-07-07",
    question="Why did the stock move on this day?",
    thread_id="some-unique-id-per-chart-click",  # reuse the same id for a follow-up in the same thread
)
print(answer.model_dump_json(indent=2))
```

## Running the API

```bash
cd backend
uvicorn app.main:app --reload
```

## Tests

```bash
cd backend
python -m pytest tests/ -v
```

Runs against a dedicated `earnings_timeline_test` database (auto-created, never the dev DB) — no extra setup needed beyond the Docker Postgres container already being up.
