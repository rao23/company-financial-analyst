# Build Tasks: Earnings Timeline AI

Generated from: `docs/DESIGN.md` (§11 Build Plan), `docs/adr/0001`–`0009`, `CONTEXT.md`
Date: 2026-07-07

Ordered by dependency — each phase builds on tables/components the previous phase created. Within a phase, tasks are independently buildable/verifiable. Per `CLAUDE.md`: every meaningful change to prompts, retrieval logic, or the agent must pass the eval harness (Phase 5) before being treated as an improvement — that gate applies to everything in Phase 4 onward, retroactively, as those phases evolve.

---

## Phase 0 — LLM Foundations

- [ ] **Context window / temperature intuition script**: a throwaway script hitting the `google-genai` SDK directly, varying `temperature` and prompt length, to build hands-on intuition before any framework is involved. Scaffolding is in `experiments/phase0_llm_foundations.py` — TODOs (picking prompts, running, observing) still need doing.
  - [ ] Try the same prompt at temperature 0 vs 1, observe variance
  - [ ] Push a prompt past a small context budget deliberately, observe truncation/error behavior

---

## Phase 1 — Data Foundation I (fundamentals + price)

- [ ] **`companies` + `company_aliases` schema and ingestion**: bulk-load from SEC's `company_tickers.json`, keyed on **CIK**, not ticker (ADR-0001).
  - [ ] `companies (cik PK, ticker, name, sector, gics, ipo_date)`
  - [ ] `company_aliases (alias, company_id)` — seed with a curated list for well-known brand/legal-name mismatches (e.g. Google → Alphabet)
  - [ ] Search/lookup query against ticker + legal name + aliases (trigram or `ILIKE` is fine for v1 volume)
- [ ] **`financial_metrics` schema with as-filed provenance** (ADR-0005): fields for `source_accession_number`, `filed_date`, `was_restated`, `restatement_filing_id`.
  - [ ] Selection rule: for each `(company, period, tag)`, take the value from the filing whose *primary* reporting period is that period, not a later comparative
  - [ ] Ingestion writes **insert-if-absent only** — never upsert-to-latest
  - [ ] 10-K/A detection sets `was_restated` metadata without touching the stored value
- [ ] **EBITDA/FCF derivation layer** (§6): `EBITDA ≈ operating_income + D&A`, `FCF = OCF − capex`, computed off as-filed figures only.
  - [ ] Correctness check against 2–3 known-good companies' publicly reported EBITDA/FCF
- [ ] **`price_history` ingestion via yfinance**
- [ ] **Pre-2009 Coverage Gap flag** (§12): a computed field/endpoint indicating whether a company's IPO predates 2009 XBRL coverage — UI-flag only, no raw-filing-text parsing in v1

---

## Phase 2 — Embeddings, Vector DB, RAG

- [ ] **`filings` + `filing_chunks` schema and chunking** (§7): split by structural Item heading first, sub-chunk only where sections are long.
- [ ] **Local embedding pipeline**: `sentence-transformers` (bge/e5), store in pgvector with `company_id`, `source_type`, `filed_date`.
  - [ ] Confirm the pgvector query operator matches the embedding model's training objective (cosine `<=>`, not L2 `<->`, for bge/e5)
- [ ] **Metadata-filtered-then-ANN retrieval**: company + date range filter always applied before the ANN search — never a global vector search.
- [ ] **Quarter-scoped retrieval smoke test**: confirm a query about one company/date range never surfaces another company's chunks

---

## Phase 3 — Data Foundation II (events + news)

- [ ] **8-K ingestion**: EDGAR submissions API filtered to form type 8-K.
- [ ] **Finnhub news client**: `company-news` endpoint, ticker + date-scoped.
  - [ ] Ingestion trigger: scheduled batch for watchlist companies, on-demand-but-cached for first search of any other company
  - [ ] Never re-fetch a window already pulled
- [ ] **`news_articles` + `news_chunks` schema**: chunked by paragraph, `source_type=news`, `trust_level=unofficial`

---

## Phase 4 — Agent (LangGraph, tool use, expanding-window retrieval)

- [ ] **Hand-rolled raw tool-use loop (throwaway exercise)**: one tool, directly against the `google-genai` SDK — message list, function-call part, execute, function-response, repeat. Purely to see the mechanism before adopting LangGraph.
- [ ] **Investigation Date derivation**: price-series click uses the clicked date as-is; fundamentals-point click uses that period's `filed_date`, not period-end.
- [ ] **Query Intent classification node** (ADR-0003): LLM classifies Move vs. Trend from wording before any retrieval tool runs; defaults to Trend on genuinely ambiguous wording.
- [ ] **Tool: `get_financials(ticker, quarter)`**
- [ ] **Tool: `get_filing_chunks(ticker, date_range, query)`**
- [ ] **Tool: `get_news(ticker, date_range)`**
- [ ] **Tool: `get_price_context(ticker, date)`** — Move magnitude vs. a trailing 5-day average baseline, not raw prior-day close
- [ ] **Tool: `get_price_trend(ticker, date)`** (ADR-0002) — backward swing-point walk returning `{direction, trend_start_date, cumulative_move_pct}`, with a noise threshold so short counter-moves don't reset the Trend Start
  - [ ] Tune and document the noise threshold (cumulative % or N consecutive days) used to detect a genuine reversal
- [ ] **Expanding-window retry graph** (14 → 90 → 180 days):
  - [ ] Deterministic conditional edge: Grounding Set empty → force-widen, never left to LLM discretion
  - [ ] LLM-judged edge: found cause's magnitude doesn't match `get_price_context`/`get_price_trend` → widen
- [ ] **Grounding Set state** (ADR-0006, ADR-0009): dedup pool of chunk IDs accumulated across all tool calls in the current Investigation Thread, reset only when a new thread starts
- [ ] **Investigation Thread / follow-up handling** (ADR-0009): follow-ups stay scoped to the same Investigation Date; full prior message history (including `tool_use`/`tool_result`) replayed as context
- [ ] **System prompt behavior rules**: always cite source (type + date), always state lag if not same-day, explicit "no clear cause found" rather than fabricating one

---

## Phase 5 — Eval Harness (merge gate from here on)

- [ ] **`eval_cases` / `eval_results` schema**: `query_type` (move/trend), `expected_trend_start_min`/`max` for trend cases
- [ ] **Hand-label 15–20 eval cases**, including at least: one litigation case, one competitor-driven case, one Move "no clear cause" case, one Trend "no clear cause" case
- [ ] **Retrieval recall@k** (programmatic)
- [ ] **Faithfulness** (LLM-as-judge): every claim traces to a retrieved chunk
- [ ] **Numeric consistency** (programmatic): cited numbers match `financial_metrics`
- [ ] **Timing-awareness** (LLM-as-judge, custom rubric): correct lag; extended for Trend cases to check the reversal cause isn't misattributed to earlier unrelated news inside the window
- [ ] **Trend Start Accuracy** (programmatic, ADR-0004): computed Trend Start falls within the hand-labeled tolerance range — not judged
- [ ] **Honesty-on-no-cause**: correct decline-to-fabricate on both Move and Trend "no clear cause" cases
- [ ] **Wire the offline suite as a merge gate**: run on every prompt/retrieval-logic/model change before calling it an improvement

---

## Phase 6 — Guardrails & Application Architecture

- [ ] **Structured output schema**: Pydantic model for `{explanation, citations, lag_days, confidence}`
- [ ] **`confidence` rubric** (ADR-0007): deterministic function of window tier resolved, primary citation's `trust_level`, and magnitude match — not LLM self-reported; distinct from the Honesty-on-no-cause case, not its lowest bucket
- [ ] **Citation existence check** (ADR-0006/0009): every `source_id` validated against the current Investigation Thread's Grounding Set; reject to "insufficient grounding" on miss
- [ ] **Input validation**: ticker/company must resolve to a real `companies` row before any tool executes; date ranges bounded
- [ ] **Untrusted-text delimiting**: filing/news text wrapped in clear delimiters in the prompt, so ingested text can't be read as an instruction
- [ ] **Caching per (company_id, Investigation Date)**: avoid recomputing an already-answered investigation

---

## Phase 7 — Frontend (Next.js)

- [ ] **Design tokens**: palette (ledger neutrals, stamp-blue accent, gold trust marker, teal/crimson semantic), Fraunces/Libre Franklin/IBM Plex Mono type system, per §14
- [ ] **Search with alias resolution**: hits the `company_aliases` lookup from Phase 1
- [ ] **Company record header**: name, ticker, CIK, sector, IPO date, Pre-2009 Coverage Gap note
- [ ] **Timeline chart**: price + fundamentals overlay, click handling that produces an Investigation Date per the Phase 4 derivation rule
- [ ] **Click-to-ask input**: single free-text field (not separate Move/Trend affordances), submits Investigation Date + question to the agent
- [ ] **Investigation Thread panel**: Move/Trend/Honesty states, citation trust tags, confidence meter, follow-up input — matching the §14 concept
- [ ] **Loading state**: skeleton/shimmer for the multi-second expanding-window agent flow — do not ship a spinner-less blocking wait
- [ ] **Responsive pass**: single-column stacking below the two-column breakpoint; 44px touch targets; dark/light theme via CSS custom properties

---

## Review

- [ ] **Design review**: check the built frontend against §14 and the mockup artifact for drift
- [ ] **Full eval suite run**: confirm Phase 5 metrics pass before considering v1 feature-complete
