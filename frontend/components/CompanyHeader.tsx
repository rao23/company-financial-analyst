import type { CompanyDetail } from "@/lib/api";

export default function CompanyHeader({ company }: { company: CompanyDetail }) {
  return (
    <header className="border-b hairline pb-4">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="font-display text-3xl text-ink">{company.name}</h1>
        <span className="font-mono text-lg text-accent">{company.ticker}</span>
      </div>
      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-ink/70">
        <div className="flex gap-1">
          <dt>CIK</dt>
          <dd>{String(company.cik).padStart(10, "0")}</dd>
        </div>
        {company.sector && (
          <div className="flex gap-1">
            <dt>Sector</dt>
            <dd>{company.sector}</dd>
          </div>
        )}
        {company.gics && (
          <div className="flex gap-1">
            <dt>GICS</dt>
            <dd>{company.gics}</dd>
          </div>
        )}
        {company.ipo_date && (
          <div className="flex gap-1">
            <dt>IPO</dt>
            <dd>{company.ipo_date}</dd>
          </div>
        )}
        {company.price_coverage_start && (
          <div className="flex gap-1">
            <dt>Coverage from</dt>
            <dd>{company.price_coverage_start}</dd>
          </div>
        )}
      </dl>
      {company.has_pre_2009_gap && (
        <p className="mt-2 text-xs text-ink/60">
          Pre-2009 fundamentals aren&apos;t shown: structured XBRL data only exists for filings after the
          SEC&apos;s 2009 mandate.
        </p>
      )}
    </header>
  );
}
