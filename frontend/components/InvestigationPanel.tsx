"use client";

import { useState } from "react";
import { askAgent, type AskResponse } from "@/lib/api";

type Exchange = {
  question: string;
  answer: AskResponse;
};

function TrustTag({ sourceType }: { sourceType: "filing" | "news" }) {
  const isOfficial = sourceType === "filing";
  return (
    <span
      className="rounded-sm px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wide"
      style={{
        color: isOfficial ? "var(--color-accent)" : "var(--color-gold)",
        border: `1px solid ${isOfficial ? "var(--color-accent)" : "var(--color-gold)"}`,
      }}
    >
      {isOfficial ? "Official" : "Unofficial"}
    </span>
  );
}

function ConfidenceMeter({ confidence }: { confidence: number }) {
  const segments = 5;
  const filled = Math.round(confidence * segments);
  return (
    <div className="flex items-center gap-1">
      <span className="font-mono text-xs text-ink/60">Confidence</span>
      <div className="flex gap-0.5">
        {Array.from({ length: segments }, (_, i) => (
          <span
            key={i}
            className="h-2 w-3"
            style={{ background: i < filled ? "var(--color-accent)" : "var(--color-hairline)" }}
          />
        ))}
      </div>
    </div>
  );
}

function AnswerCard({ exchange }: { exchange: Exchange }) {
  const { answer } = exchange;
  return (
    <div className="border-t hairline pt-3">
      <p className="font-mono text-xs text-ink/60">{exchange.question}</p>
      <p className="mt-1 font-display italic text-ink">{answer.explanation}</p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {answer.no_clear_cause ? (
          <span className="rounded-sm border border-dashed hairline px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wide text-ink/60">
            No clear cause found
          </span>
        ) : (
          answer.confidence != null && <ConfidenceMeter confidence={answer.confidence} />
        )}
        {answer.lag_days != null && (
          <span className="font-mono text-xs text-ink/60">Lag: {answer.lag_days}d</span>
        )}
      </div>
      {answer.citations.length > 0 && (
        <ul className="mt-2 space-y-1">
          {answer.citations.map((citation, i) => (
            <li key={i} className="flex items-start gap-2 text-xs">
              <TrustTag sourceType={citation.source_type} />
              <span className="text-ink/80">&ldquo;{citation.quote}&rdquo;</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function InvestigationPanel({ ticker, investigationDate }: { ticker: string; investigationDate: string }) {
  const [threadId, setThreadId] = useState<string | undefined>(undefined);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    try {
      const answer = await askAgent(ticker, investigationDate, trimmed, threadId);
      setThreadId(answer.thread_id);
      setExchanges((prev) => [...prev, { question: trimmed, answer }]);
      setQuestion("");
    } catch {
      setError("Something went wrong asking the agent. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="border-t hairline pt-4">
      <p className="font-mono text-xs text-ink/60">Investigating {ticker} — {investigationDate}</p>

      <div className="mt-3 space-y-3">
        {exchanges.map((exchange, i) => (
          <AnswerCard key={i} exchange={exchange} />
        ))}
      </div>

      {loading && <p className="mt-3 text-sm text-ink/60">Investigating — this can take a few seconds…</p>}
      {error && <p className="mt-3 text-sm" style={{ color: "var(--color-down)" }}>{error}</p>}

      <form onSubmit={handleSubmit} className="mt-4 flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={exchanges.length === 0 ? "Why did the stock move?" : "Ask a follow-up…"}
          disabled={loading}
          className="flex-1 border-b hairline bg-transparent px-1 py-2 text-sm text-ink placeholder:text-ink/40 focus:outline-none focus:border-accent disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="px-3 py-2 text-sm font-mono text-accent disabled:opacity-40"
        >
          Ask
        </button>
      </form>
    </section>
  );
}
