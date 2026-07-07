# Earnings Timeline AI

A company research site correlating fundamentals/price timelines with SEC filings and news, via a grounded RAG agent.

## Language

**Company**:
The canonical entity for a public filer, identified internally by its SEC **CIK** (a permanent, never-reused identifier assigned by the SEC). All other tables (`financial_metrics`, `filing_chunks`, `news_articles`, `price_history`) reference a Company by this identity, not by ticker.
_Avoid_: using ticker as the join key / identity.

**Ticker**:
A mutable trading symbol belonging to a Company at a point in time. Tickers can change (rebrands, relistings) and can be reused by an unrelated Company after delisting — so they're a searchable/display attribute, never an identity.
_Avoid_: treating ticker as stable or unique over time.

**Company Alias**:
A curated colloquial/brand name (e.g. "Google") mapped to its canonical Company (e.g. Alphabet Inc.) for search purposes only. Resolved via a lookup table, not an LLM call — the universe of filers is finite and mostly static, so this is a one-time curation/ingestion concern, not a runtime inference one.
_Avoid_: conflating this with legal name matching, which is exact-ish; aliases exist specifically where brand name and legal name diverge.

**Investigation Date**:
The single date anchor passed to the agent when a user clicks a chart point, derived differently depending on which series was clicked. A click on the **price** series (daily) uses the clicked date as-is. A click on a **fundamentals** point (quarterly) uses that period's filing `filed_date`, not its period-end date — the market can't react to a number before it's disclosed, so using period-end would send the expanding-window search hunting for causes before the information was public.
_Avoid_: "the clicked date" as if it's always a raw x-axis value; for fundamentals points it's a derived lookup, not the point's literal position.

**Move**:
A price change anchored to a single Investigation Date, computed against a smoothed baseline (trailing 5-day average price just prior to the Investigation Date) rather than the single prior day's close — this filters out day-to-day noise in the baseline without changing what's being explained. The unit of explanation for a point query — "why did the stock do X on this day."
_Avoid_: using this interchangeably with Trend; a Move is still anchored to one date, a Trend's scope (its start) is discovered.

**Trend**:
A directional run in price leading up to an Investigation Date, whose start is *discovered*, not fixed-window. The unit of explanation for an open-ended query like "why is it trending down?" See Trend Start.
_Avoid_: a fixed calendar lookback (e.g. "the last 30 days") — that's not what defines a Trend here.

**Trend Start**:
The most recent swing point (local peak, if now declining; local trough, if now rising) before the Investigation Date, found by walking backward and accumulating directional return until a reversal exceeds a noise threshold. Short-lived counter-moves under that threshold (e.g. a one-day bounce during an overall decline) don't reset the Trend Start.
_Avoid_: treating every local wiggle as a new trend boundary — the threshold exists specifically to filter that noise out.

**Trend Start Accuracy**:
An eval metric (sibling to Retrieval Recall, Faithfulness, etc. in §9) that checks whether the agent's computed Trend Start falls within a hand-labeled tolerance range (`expected_trend_start_min`/`max`) for a Trend eval case. Scored programmatically as an interval containment check, not by an LLM judge — swing-point detection is threshold-tuned, so exact-date matching would be brittle, and date/numeric comparison isn't a task suited to an LLM judge anyway.
_Avoid_: routing this through the Faithfulness or Timing-awareness LLM-judge rubrics; those still apply separately to judge whether the *explanation* correctly attributes the reversal cause (vs. earlier, unrelated news inside the window), which is a distinct check from whether the date itself is right.

**As-Filed Value**:
For a given `(company, period, tag)`, the figure taken from the filing whose *primary* reporting period is that period — not from a later filing that merely repeats it as a prior-year/prior-quarter comparative. This is the only value ever stored in `financial_metrics`; it is written once via insert-if-absent during ingestion and never overwritten on refresh, even if a later filing reports a different number for that same period.
_Avoid_: "the latest known value for this period" — that framing is precisely the wrong default (see Restatement).

**Restatement**:
A later filing (typically a 10-K/A, or a comparative in a subsequent 10-K/10-Q) reporting a different figure for a period whose As-Filed Value is already stored. Never overwrites the As-Filed Value; recorded as metadata only (`was_restated` + a reference to the restating filing) so the UI/agent can footnote it without changing what's charted.
_Avoid_: treating a restatement as a correction to apply — the whole point of As-Filed Value is showing what the timeline looked like at the time, not the corrected-with-hindsight version.

**Grounding Set**:
The running, deduped pool of chunk IDs returned by *any* tool call made so far within the current Investigation Thread — accumulated across expanding-window retries (14/90/180-day) and across every follow-up in that thread, not reset per message. The citation-existence check (§10) validates every cited `source_id` against this pool, so a citation grounded by an early narrow-window call, or by an earlier message in the same thread, still validates without forcing a redundant re-retrieval. Resets only when a new Investigation Thread starts (i.e. the user clicks a new point).
_Avoid_: checking citations against only the last tool call's output, or resetting the pool on every follow-up message — both would spuriously reject valid, already-established citations.

**Investigation Thread**:
The full follow-up conversation anchored to a single Investigation Date, started by a chart click. Follow-ups within a thread ("was that related to the earnings report?") stay scoped to that same date — the agent doesn't infer an implicit new date from wording. To ask about a different point in time, the user clicks again, starting a new thread with its own fresh Grounding Set.
_Avoid_: treating every follow-up message as implicitly able to shift to a new point in time; that requires conversational temporal-reference resolution, which is explicitly out of scope — an explicit click is what supplies a new Investigation Date.

**Pre-2009 Coverage Gap**:
For a Company whose IPO predates the 2009 XBRL mandate, the period before structured XBRL data exists. v1 scope is a UI flag stating the gap explicitly on the timeline — not raw filing-text parsing to backfill it. Backfilling via text parsing is out of v1 scope entirely, not a partial/best-effort attempt.
_Avoid_: silently truncating the timeline at the coverage boundary with no indication why; the flag is the feature, not a placeholder for parsing that's coming later in v1.

**Confidence**:
A field in the structured output schema, derived by a deterministic rubric off signals the agent already produces — which expanding-window tier resolved the answer (14/90/180-day), the trust_level of the primary citation, and whether the price move's magnitude matches the found cause's apparent significance — not a number the LLM self-reports. Self-reported LLM confidence is known to be poorly calibrated (typically overconfident), and this field lives in the guardrails/output-validation layer (§10) alongside other checks the project has consistently made programmatic rather than model-asserted.
_Avoid_: a "no clear cause found" answer being just the lowest Confidence bucket — that's a distinct, explicit Honesty-on-no-cause case (§9), not merely "low confidence."

**Query Intent**:
The classification of a user's free-text question, paired with an Investigation Date, into either a Move query or a Trend query. Determined by the LLM from wording (e.g. "why did it drop here" → Move; "why is it trending down" → Trend), not by separate UI affordances — there's a single free-text input next to the chart, not two distinct entry points. On genuinely ambiguous wording (e.g. "what happened here?"), the classifier defaults to Trend rather than Move, and rather than asking a clarifying question first.
_Avoid_: assuming the query type is implicit in what was clicked; the click only supplies the Investigation Date, wording supplies the Query Intent.
