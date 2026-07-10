# Earnings Timeline AI — Design Doc

**Roadmap fit:** Phase 3 (RAG, embeddings, vector DB, eval) + Phase 4 (agents, tool use, application architecture) + Phase 5 (guardrails, output validation).
**Relationship to Stock Insight AI:** sibling project, on hold in favor of this one. Reuses the same core stack (Postgres + pgvector, FastAPI, Next.js) and the same "tag every chunk by source_type + trust level" discipline from the claim-checker design, but drops YouTube scraping / creator credibility scoring — this is the faster-to-ship version of the same skill set.

**Terminology and decisions:** see `CONTEXT.md` for the domain glossary (Company/Ticker identity, Investigation Date, Move/Trend, Grounding Set, etc.) and `docs/adr/` for the reasoning behind decisions referenced below (cited inline as ADR-000X).

---

## 1. Goal

A company research site: search any public company, see side-by-side historical timelines (stock price vs. revenue, EBITDA, FCF, margins, and other fundamentals) since IPO or since XBRL coverage began. Click any point on the timeline and an agent answers "why did this happen here" — grounded in SEC filings, material-event disclosures, and news, not the model's own memory.

---

## 2. Feature Set

| Feature | v1? |
|---|---|
| Search a company by name/ticker (alias-aware, e.g. "Google" → Alphabet Inc.) | ✅ |
| Fundamentals timeline (revenue, EPS, EBITDA, FCF, margins) | ✅ |
| Side-by-side stock price overlay on the same timeline | ✅ |
| Click a point + free-text question → agent classifies intent and explains, with citations | ✅ |
| **Move query** — explain a single day's price action (ADR-0003) | ✅ |
| **Trend query** — explain an open-ended directional run, discovering its own start (ADR-0002) | ✅ |
| Expanding-window causal search (handles delayed-effect causes) | ✅ |
| Eval harness (retrieval recall, faithfulness, numeric consistency, timing-awareness, trend start accuracy) | ✅ |
| Output validation / guardrails on agent responses | ✅ |
| Competitor-aware news search (expand beyond the ticker itself) | Stretch |

---

## 3. Architecture

```
Next.js frontend (search + timeline charts + click-to-ask panel)
        |
        v
FastAPI backend
  - bulk ingestion (SEC data sets, one-time + quarterly refresh)
  - derivation layer (EBITDA, FCF, margins)
  - RAG retrieval (quarter/date-scoped, expanding window)
  - agent loop (LangGraph, tool use, output validation)
  - eval harness (offline suite + online sampling)
        |
        v
Postgres + pgvector
  - companies, financial_metrics, price_history
  - filing_chunks (10-K/10-Q/8-K text + embeddings, tagged by source_type)
  - news_articles (Finnhub, tagged by source_type)
  - eval_cases, eval_results
```

No paid APIs. Docker Compose ties it together locally.

---

## 4. Data Sources

| Data | Source | Notes |
|---|---|---|
| Structured financials (revenue, EPS, assets, all XBRL facts, all filers) | SEC **Financial Statement Data Sets** (`sec.gov/dera/data/financial-statement-data-sets.html`) — quarterly ZIP, tab-delimited | Free, no key. Bulk-load once, then quarterly refresh — avoids per-company rate-limited calls entirely. Coverage starts ~2009 (XBRL mandate); pre-2009 "since IPO" history for older companies means parsing raw filing text instead, not structured XBRL — flag this gap in the UI rather than silently truncating. |
| Full XBRL fact history per company (fallback/backfill) | SEC bulk `companyfacts.zip` (`sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip`) | Free, no key, same rate-limit rules (10 req/s if hitting per-company API instead). |
| 10-K / 10-Q raw text (MD&A narrative) | EDGAR full-text search + submissions API | Free, `User-Agent` + contact email required. Structural chunking by Item heading (see §7). |
| **8-K material-event filings** | EDGAR submissions API, filtered to form type 8-K | Event-triggered (filed within 4 business days of specific enumerated triggers: M&A, exec departures, guidance changes, material legal outcomes). This is the SEC-native source closest to "something happened on this date." |
| Stock price history | `yfinance` | Free, unofficial. |
| **Financial news, ticker + date-scoped** | **Finnhub** `company-news?symbol=X&from=...&to=...` | Free tier: 60 calls/**minute** (not per day) — generous enough for bulk ingestion. Chosen over Alpha Vantage News & Sentiment (free tier capped at 25 requests/day — too thin) and GDELT (free, huge historical event index, but its easy-query DOC 2.0 API only officially guarantees ~3 months of lookback). Covers the gap SEC filings can't: analyst actions, competitor moves, litigation outcomes before/without a filing, macro news. |

**News ingestion trigger (same pattern as filings, not ad-hoc-and-discarded):** scheduled batch pull for tracked/watchlist companies, on-demand-but-cached for any other company on first search — always chunked, embedded, and stored either way, never re-fetched for a window already pulled. Storing isn't about quota (60/min leaves plenty of headroom) — it avoids recomputing embeddings on repeat clicks, keeps citations durable for the eval harness after the fact, and protects against source articles disappearing or getting paywalled later.

---

## 5. Data Model (Postgres)

- `companies` (**cik** [PK], ticker, name, sector, gics, ipo_date) — keyed on SEC CIK, not ticker: tickers are reused after delisting and change on rebrands, CIK is permanent and never reused (ADR-0001). Ticker is an indexed, mutable lookup/display attribute.
- `company_aliases` (alias, company_id) — curated brand-name-to-legal-name mappings for search (e.g. "Google" → Alphabet Inc.), not LLM-resolved at query time (ADR-0001)
- `financial_metrics` (company_id, period, revenue, eps, ebitda, fcf, margins, `source_accession_number`, `filed_date`, `was_restated`, `restatement_filing_id`, ...) — `ebitda`/`fcf` computed via the derivation layer (§6). Every figure is the **As-Filed Value**: selected from the filing whose primary reporting period is that period (not a later comparative), written insert-if-absent on refresh and never overwritten by a later restatement — a later 10-K/A only sets `was_restated`/`restatement_filing_id` as metadata (ADR-0005)
- `price_history` (company_id, date, close, volume)
- `filings` (company_id, type [10-K/10-Q/8-K/10-K-A], period, filed_date, source_url, raw_text)
- `filing_chunks` (filing_id, section, chunk_text, embedding, source_type=`filing`, trust_level=`official`)
- `news_articles` (company_id, published_at, headline, body, source_url, source_type=`news`, trust_level=`unofficial`)
- `news_chunks` (article_id, chunk_text, embedding) — same chunk+embed treatment as filings, just a different `source_type`
- `eval_cases` (company_id, investigation_date, **query_type** [move/trend], expected_cause_type, expected_source_ref, `expected_trend_start_min`, `expected_trend_start_max`, notes) — the hand-labeled test set; trend cases use the min/max range instead of a single expected date (ADR-0004)
- `eval_results` (eval_case_id, run_id, retrieval_hit, faithfulness_score, numeric_consistency, timing_correct, **trend_start_accuracy**, honesty_correct, run_date) — all six §9 metrics get a column, not just the four in this section's original list

Every chunk-bearing table carries `source_type` + `trust_level` so retrieval and the agent's prompt can weight/label official vs. unofficial sources differently.

---

## 6. Derivation Layer (EBITDA / FCF)

XBRL doesn't tag EBITDA or FCF directly — computed from raw tagged facts:
- `EBITDA ≈ operating_income + depreciation_and_amortization`
- `FCF = operating_cash_flow − capital_expenditures`

Computed off **as-filed** figures, not restated ones — a chart showing a 2019 quarter using 2024-restated numbers is a lookahead bug, not a feature, given the whole point is "what did the timeline look like at that point in time." This as-filed discipline isn't unique to EBITDA/FCF — it applies to every figure in `financial_metrics` (§5) and is enforced by insert-if-absent ingestion, never upsert-to-latest (ADR-0005).

---

## 7. Chunking & Retrieval

- Filings split by structural Item heading first (MD&A, Risk Factors, etc.), then sub-chunked with overlap only where sections are long.
- News articles chunked by paragraph (no formal structure to exploit).
- Every chunk embedded (local `bge`/`e5` via `sentence-transformers` — no embedding API cost) and stored in pgvector with `company_id`, `source_type`, `filed_date`/`published_at`.
- Retrieval is always metadata-filtered first (company + date range), then ANN search within that filtered set — never a global search across the whole corpus.

---

## 8. Agent Design

**Investigation Date derivation:** the date passed into the agent depends on which chart series was clicked. A click on the **price** series (daily) uses the clicked date as-is. A click on a **fundamentals** point (quarterly) uses that period's `filed_date`, not its period-end date — the market can't react to a number before it's disclosed, so period-end would send the expanding-window search hunting for causes before the information was public.

**Query Intent classification:** a single free-text input sits next to the chart (not two separate UI affordances) — the user pairs an Investigation Date (from the click) with a free-text question, and an LLM routing step classifies it as a **Move** query ("why did it drop here") or a **Trend** query ("why is it trending down") before any retrieval tool runs (ADR-0003). On genuinely ambiguous wording, the classifier defaults to Trend rather than asking a clarifying question first.

**Follow-ups and Investigation Threads:** a click starts an **Investigation Thread** — the full follow-up conversation scoped to that click's Investigation Date. Follow-up questions within the thread stay anchored to that same date; the agent never infers an implicit new date from wording. To ask about a different point in time, the user clicks again, starting a fresh thread. The prior thread's full message history (including earlier `tool_use`/`tool_result` exchanges) is replayed as context so references like "that" resolve correctly (ADR-0009).

**Tools:**
- `get_financials(ticker, quarter)`
- `get_filing_chunks(ticker, date_range, query)` — pulls from `filing_chunks`, tagged official
- `get_news(ticker, date_range)` — pulls from `news_chunks`, tagged unofficial
- `get_price_context(ticker, date)` — for a **Move** query: the price change at the Investigation Date against a smoothed baseline (trailing 5-day average price just prior), not a raw prior-day close, used by the agent to self-calibrate whether a found cause is "big enough" to explain the move
- `get_price_trend(ticker, date)` — for a **Trend** query: walks backward from the Investigation Date, returning `{direction, trend_start_date, cumulative_move_pct}`. The **Trend Start** is the most recent swing point (local peak/trough) before a reversal exceeding a noise threshold — short-lived counter-moves under that threshold don't reset it, so a brief bounce during an overall decline doesn't get misread as the trend's actual start (ADR-0002)

**Expanding-window retrieval (the delayed-causality fix):** the agent starts with a narrow window (`date − 14 days` to `date`). If nothing salient is found, or the found cause's apparent significance doesn't match the magnitude from `get_price_context`, re-call the tools with a wider window (90 days, then 180 days) before answering. The final answer must state the actual event date and the lag explicitly ("this appears tied to a guidance cut disclosed 47 days earlier") rather than implying same-day causality. Concrete cases this is designed to catch:
- **Litigation outcome:** often news-first (court reporting is immediate) and filing-second or never, depending on materiality — the news tool is the primary leg here, not the filing tools.
- **Competitor product launch:** doesn't appear in the company's own filings at all except retrospectively in MD&A ("increased competitive pressure from X") — this is a news-only signal, and a stretch goal is expanding news search to competitor tickers, not just the searched company's own ticker.
- **Slow-building narrative** (e.g., accumulating analyst concern): may have no single explanatory document. The agent must be allowed to say "no clear single triggering event found in the past N months — this may reflect a broader trend" rather than fabricating a cause. This honesty case is itself a row in the eval harness (§9).

**Grounding Set:** LangGraph state accumulates a deduped pool of every chunk ID returned by any tool call so far in the current Investigation Thread — across all expanding-window retries and across every follow-up in that thread, not just the most recent call — and resets only when a new thread starts (a new chart click). The citation-existence check (§10) validates against this full pool, so a citation grounded by an early narrow-window call, or an earlier message in the thread, still validates without a redundant re-retrieval (ADR-0006, ADR-0009).

**System prompt behavior rules:** always cite source (type + date), always state lag if the cause isn't same-day, expand window before answering if the found cause doesn't match the move's magnitude, explicitly say "no clear cause found" rather than inventing one.

**Orchestration: LangGraph.** Build the agent in LangGraph rather than a hand-rolled raw tool-use loop — this is an explicit learning goal, and as of LangChain v0.3+, LangGraph is the officially recommended way to build agents (the older `AgentExecutor` pattern is in maintenance-only mode). LangGraph is model-agnostic orchestration — it doesn't ship its own LLM, it calls out to **Google Gemini** via the `langchain-google-genai` package's `ChatGoogleGenerativeAI` class (ADR-0010 — switched from Claude for cost reasons; free tier, accepted tradeoff on tool-calling reliability). The expanding-window retry logic above maps naturally onto LangGraph's actual design case: nodes for each tool/step, conditional edges based on state ("if retrieval confidence is low, route to the wider-window node; otherwise route to generate-answer").

Before building the LangGraph version, do a short (~1 hour) throwaway exercise hand-rolling the raw tool-use loop for a single tool directly against the `google-genai` SDK — message list, function-call part, execute, function-response, repeat. Purely to see the mechanism LangGraph abstracts before adopting the framework for the real build.

---

## 9. Eval Harness

**Offline (regression suite, run like CI):** a hand-labeled `eval_cases` set (~15–20 known historical price moves with documented causes, including at least one litigation case, one competitor-driven case, one Move "no clear cause" case, and one Trend "no clear cause" case), covering both Move and Trend query types (`query_type` in §5). Run the full suite on every prompt, retrieval-logic, or model change, before treating that change as an improvement. Metrics:
- Retrieval recall@k — did the correct source show up in top-k for the given `(ticker, date)`
- Faithfulness (LLM-as-judge) — does every claim in the answer trace to a retrieved chunk
- Numeric consistency (programmatic, no judge) — do cited numbers match `financial_metrics`
- Timing-awareness (LLM-as-judge, custom rubric) — is the stated lag between event and price move correct; for Trend cases, does the explanation correctly attribute the reversal cause rather than misattributing it to earlier, unrelated news that happens to fall inside the discovered window
- **Trend Start Accuracy (programmatic, no judge)** — does the agent's computed Trend Start fall within the hand-labeled `expected_trend_start_min`/`max` range for a Trend case; a plain interval check, not LLM-judged, since swing-point detection is threshold-tuned and exact-date matching would be brittle (ADR-0004)
- Honesty-on-no-cause — does the agent correctly decline to fabricate a cause on the "no clear cause" eval cases, for both Move (no single triggering event) and Trend (slow-building narrative with no single discoverable reversal event)

**Online (production monitoring, sampled, continuous):** score 100% of responses where a tool call returned empty/thin results, responses with a thumbs-down, and responses on tickers/dates outside the offline eval set. Sample ~5–10% of everything else. Track the same metrics over time in production, not just at deploy time — this is what catches silent drift a static test set won't.

**Cadence:** offline suite runs on every meaningful change (prompt edit, retrieval logic change, model swap) — treat it as a merge gate, same role as a CI test suite. Online sampling runs continuously against live traffic, reviewed weekly, harvesting new hard cases into the offline suite over time.

---

## 10. Output Validation / Guardrails

- **Structured output schema:** the agent's final answer is constrained to a schema (via structured-output/JSON mode), not free text — fields like `explanation`, `citations: [{source_type, source_id, quote}]`, `lag_days`, `confidence`. Enforced with a Pydantic model on the backend.
  - **`confidence` is derived, not self-reported:** computed by a deterministic rubric off signals the agent already produces — which expanding-window tier resolved the answer (14/90/180-day), the `trust_level` of the primary citation, and whether the price move's magnitude matches the found cause's apparent significance. LLM self-reported confidence is poorly calibrated (typically overconfident), so this stays out of the model's hands, consistent with the rest of this section (ADR-0007). A "no clear cause found" answer is the separate Honesty-on-no-cause case (§9), not simply the lowest confidence bucket.
- **Citation existence check (programmatic):** every `source_id` in the response must match a chunk in the current Investigation Thread's **Grounding Set** (§8) — the accumulated pool from every tool call made so far in that thread, not just the most recent one — if the agent cites something never retrieved, reject and fall back to "insufficient grounding" (ADR-0006, ADR-0009).
- **Input validation:** ticker must exist in `companies` before any tool executes; date range params are bounded.
- **Treat ingested text as untrusted:** filing and news text originates outside your control — wrap it in clear delimiters when inserted into the prompt so a stray adversarial phrase in a news article can't be read as an instruction to the model.

---

## 11. Build Plan

| Phase | Concepts | Focus |
|---|---|---|
| 0 | LLM foundations | Quick script: context window/temperature intuition |
| 1 | Data foundation | Bulk-load SEC Financial Statement Data Sets + yfinance; EBITDA/FCF derivation; Tab 1 UI |
| 2 | Embeddings, vector DB, RAG | Chunking (filings), embedding, pgvector, quarter-scoped retrieval |
| 3 | Data foundation (cont.) | 8-K ingestion + Finnhub news ingestion, tagged by source_type/trust_level |
| 4 | Agents, prompt engineering, context construction | LangGraph agent, tool definitions, expanding-window retrieval, click-to-ask UI |
| 5 | Evals | Offline harness (recall, faithfulness, numeric consistency, timing-awareness, honesty) |
| 6 | Guardrails, application architecture | Output schema validation, citation existence check, input validation, caching per (ticker, date) |

---

## 12. Known Limitations

- Pre-2009 structured financials require parsing raw filing text, not XBRL — coverage gap for older IPOs. **v1 scope is a UI flag stating the gap explicitly, not text-parsing to backfill it** — backfilling is out of scope entirely for v1, not a partial/best-effort attempt.
- EBITDA/FCF are derived, not directly filed — derivation logic itself needs a small correctness check against a few known-good companies before trusting it broadly.
- Finnhub's historical news depth for older events isn't guaranteed to be exhaustive — treat news coverage as supplementary, not a complete historical record.
- Not every price move has a discoverable single cause — the agent is expected to say so rather than fabricate one; this is a feature of the design (see §8, §9), not a gap to "fix" away.
- Filing text extraction (§7) drops images entirely — `get_text()` only walks text nodes, so content that exists only in an image (most notably 10-K "Stock Performance Graph" sections, occasionally MD&A charts) is invisible to chunking/embedding/the agent. Not treated as a gap worth solving: the numbers that matter for this project come from XBRL facts (§5/§6) and native-HTML tables (lossy but present as flattened text), not from chart images, and price history is already sourced directly from `yfinance`.

---

## 13. Repo Structure

```
company-financial-analyst/
├── README.md
├── CLAUDE.md
├── docs/DESIGN.md
├── docker-compose.yml
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── models/          # SQLAlchemy models
│   │   ├── ingestion/        # SEC bulk loader, 8-K fetcher, Finnhub client, yfinance
│   │   ├── derivation/        # EBITDA/FCF computation
│   │   ├── rag/                # chunking, embeddings, retrieval
│   │   ├── agent/               # LangGraph nodes/graph, tool defs, output validation
│   │   ├── eval/                  # offline harness, online sampling hooks
│   │   └── api/                    # FastAPI routers
│   └── tests/
├── frontend/
│   ├── package.json
│   └── app/                  # Next.js: search, timeline charts, click-to-ask panel
└── .gitignore
```

---

## 14. UI Design System (Concept)

An early visual concept was mocked up for the company page (chart + click-to-ask + Investigation Thread) to pin down a direction before the Phase 4 Next.js build. Framing: an annotated financial exhibit — a ledger-toned "record" for one company — rather than a generic SaaS dashboard, since the product's whole premise is verifiable evidence, not a chat widget bolted onto a chart.

**Palette** (light/dark both fully specified, not inverted):
- `ink` — near-black cool charcoal, primary text/structure
- `paper`/`surface` — cool ledger-grey ground (not warm cream)
- `accent` (stamp blue) — the single spent accent: interactive elements, links, the `official` trust tag
- `gold` — reserved exclusively for the `unofficial` trust tag, never used decoratively
- `up` / `down` (teal / crimson) — strictly semantic for price direction, kept separate from the accent

**Type**: Fraunces (a characterful serif) used sparingly — the company-record headline and short italic "pull lines" in agent explanations — paired with Libre Franklin for all UI/body text and IBM Plex Mono for every date, price, ticker, and CIK, set with tabular numerals throughout.

**Layout**: an asymmetric two-column grid — a narrow metadata "spine" (sector, GICS, coverage dates, sources) beside the chart and Investigation Thread — hairline-ruled rather than card-and-shadow based, echoing a ruled ledger sheet.

**Key UI patterns that encode design decisions directly, not just visually:**
- The Move / Trend / No-clear-cause states (§8, ADR-0002/0003) are shown as tabs whose selection also re-highlights the corresponding annotation on the chart (the clicked point, the shaded Trend Start band, or a muted unringed dot) — reinforcing that the chart and the answer are one system.
- Citations show a blue "Official" or gold "Unofficial" tag, surfacing `trust_level` directly rather than burying it in prose.
- `confidence` (ADR-0007) renders as a segmented meter, not a color-coded traffic light — it's a derived rubric, not a vibe.
- The Honesty-on-no-cause case (§9) deliberately omits the confidence meter entirely and uses a dashed pill instead of a solid one, so it reads as structurally distinct from "low confidence," not a variant of it.
- The Pre-2009 Coverage Gap (§12) surfaces as a calm inline note under the company header, not a warning banner.
