# Company Financial Analyst (Earnings Timeline AI)

Company research site: search any public company, see side-by-side historical timelines of stock price vs. fundamentals (revenue, EBITDA, FCF, margins), and click any point on the chart to have a LangGraph agent explain the move — grounded in SEC filings (10-K/10-Q/8-K) and news, with citations.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design doc, [`docs/TASKS.md`](docs/TASKS.md) for the phased build plan, [`CONTEXT.md`](CONTEXT.md) for the domain glossary, and [`docs/adr/`](docs/adr/) for architecture decisions.

## AI concepts demonstrated

RAG over SEC filings and news (structural chunking, company/date-scoped pgvector retrieval), LangGraph agent with expanding-window causal search, LLM-as-judge + programmatic eval harness with hand-labeled ground truth, output validation/guardrails on structured agent responses (citation-existence check, date-range bounding, untrusted-text delimiting), a per-(company, date, question) answer cache versioned against the eval harness, and a Next.js frontend wiring all of the above into a click-to-ask UI.

## Status

Backend complete through Phase 6 (eval harness + guardrails); Phase 7 (frontend) in progress. See `docs/TASKS.md` for the full checklist.

- **Phase 0** — Gemini API foundations (`experiments/phase0_llm_foundations.py`)
- **Phase 1** — Company/ticker ingestion, XBRL financial metrics, EBITDA/FCF derivation, price history, Pre-2009 Coverage Gap flag
- **Phase 2** — Filing fetch + Item-heading chunking, local embedding pipeline (pgvector), metadata-filtered retrieval
- **Phase 3** — 8-K ingestion, Finnhub news client + window-dedup, `news_articles`/`news_chunks` schema
- **Phase 4** — LangGraph agent: Query Intent classification, 5 data tools, expanding-window retry (14/90/180 days), Grounding Set, Investigation Thread/follow-ups, structured output with derived confidence and a citation-existence guardrail
- **Phase 5** — Offline eval harness: 4 programmatic + 2 LLM-as-judge metrics, 11 hand-labeled `EvalCase` rows (litigation, competitor-driven, and both Move/Trend no-clear-cause cases) verified against real ingested filings/news; a `label_case.py` CLI to add more
- **Phase 6** — Guardrails: structured output schema, derived-not-self-reported confidence, citation-existence check, ticker + date-range input validation, untrusted-text delimiting in the agent prompt, and a versioned per-(company, date, question) answer cache
- **Phase 7** (in progress) — Next.js frontend: search, company header, price+fundamentals timeline chart, and a working click-to-ask panel (`/agent/ask`) with citations/trust tags/confidence meter. Not yet done: design polish against §14, loading-state refinement, responsive pass
- Full-universe bulk ingestion has been run once already: price history, 8-K filings, and 5 years of news (Massive/Polygon) for all ~8,000 companies in `companies` — see `backend/app/ingestion/bulk_*.py`. Filing/news embeddings are currently scoped to the 11 eval-set companies (`app.rag.embed_chunks <TICKERS...>`); the rest of the ~4.5M-chunk backlog hasn't been embedded yet.

Tests cover the deterministic logic across every phase (ingestion, derivation, chunking, embedding, retrieval, eval metrics, the agent's tools/confidence rubric/guardrails/cache, the graph's control flow, and the API routes) — see `backend/tests/` (133 passing). Every phase ships with test coverage before being marked complete. LLM calls (Query Intent, the tool-use loop, the eval judges) are additionally verified live against the real Gemini API — see `docs/TASKS.md` for specifics.

Requires free API keys for Finnhub (supplementary news), Massive/Polygon (primary news, 5 years of history), and Gemini (agent + eval judges) in the root `.env` — `FINNHUB_API_KEY`, `MASSIVE_API_KEY`, `GEMINI_API_KEY`. Note: Gemini's free tier caps `gemini-2.5-flash` at 20 requests/day per project, separate from its per-minute limit — a single agent investigation can burn 3–6+ of that in one go (Query Intent + one call per tool-use round), so this is easy to exhaust during a short testing session.

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
python -m app.rag.embed_chunks                                # embed every filing_chunks/news_chunks row missing a vector
python -m app.rag.embed_chunks AAPL TSLA NVDA                 # or scope to specific tickers -- fully incremental either way

# Phase 3 — 8-Ks, news
python -m app.ingestion.sec_8k <CIK>                           # ingest every 8-K on file for a company
python -m app.ingestion.finnhub_news <TICKER> <FROM:YYYY-MM-DD> <TO:YYYY-MM-DD>
python -m app.ingestion.massive_news <TICKER> <FROM:YYYY-MM-DD> <TO:YYYY-MM-DD>  # primary news source, 5yr history
```

### Full-universe bulk backfill

These are one-time, long-running jobs over every company in `companies` (already run once against this dev DB) — resumable, so re-running skips whatever's already ingested:

```bash
python -m app.ingestion.bulk_price_history
python -m app.ingestion.bulk_8k             # rate-limited to stay under SEC's 10 req/sec fair-access policy
python -m app.ingestion.bulk_massive_news
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

Exposes `/companies/search`, `/companies/{cik}`, `/companies/{cik}/timeseries`, and `/agent/ask` (the click-to-ask endpoint — wraps the cached agent call, see `app/agent/cache.py`). CORS is enabled for `http://localhost:3000` (dev only).

## Running the frontend

```bash
cd frontend
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to http://localhost:8000
npm install
npm run dev
```

Open `http://localhost:3000`, search a company, and click a point on the price chart to ask the agent why it moved. Only works end-to-end for companies whose filing/news chunks have been embedded (see the bulk backfill note above) — everything else will just show an empty/no-clear-cause answer since retrieval has nothing to find.

## Tests

```bash
cd backend
python -m pytest tests/ -v
```

Runs against a dedicated `earnings_timeline_test` database (auto-created, never the dev DB) — no extra setup needed beyond the Docker Postgres container already being up.
