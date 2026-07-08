# Company Financial Analyst (Earnings Timeline AI)

Company research site: search any public company, see side-by-side historical timelines of stock price vs. fundamentals (revenue, EBITDA, FCF, margins), and click any point on the chart to have a LangGraph agent explain the move — grounded in SEC filings (10-K/10-Q/8-K) and news, with citations.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design doc, [`docs/TASKS.md`](docs/TASKS.md) for the phased build plan, [`CONTEXT.md`](CONTEXT.md) for the domain glossary, and [`docs/adr/`](docs/adr/) for architecture decisions.

## AI concepts demonstrated

RAG over SEC filings (structural chunking, quarter/date-scoped pgvector retrieval), LangGraph agent with expanding-window causal search, LLM-as-judge + programmatic eval harness, output validation/guardrails on structured agent responses.

## Status

Backend data foundation complete through Phase 2. See `docs/TASKS.md` for the full checklist.

- **Phase 0** — Gemini API foundations (`experiments/phase0_llm_foundations.py`)
- **Phase 1** — Company/ticker ingestion, XBRL financial metrics, EBITDA/FCF derivation, price history, Pre-2009 Coverage Gap flag
- **Phase 2** — Filing fetch + Item-heading chunking, local embedding pipeline (pgvector), metadata-filtered retrieval
- **Phase 3** (next) — 8-K ingestion, Finnhub news client
- **Phase 4+** — LangGraph agent, eval harness, frontend — not started

Tests now cover the deterministic logic added in Phase 2 (chunking, EBITDA/FCF derivation, retrieval filters) — see `backend/tests/`. Going forward, every phase ships with test coverage before being marked complete.

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
python -m app.rag.embed_chunks                                # embed any chunks missing a vector
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
