"use client";

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CompanyTimeseries } from "@/lib/api";

type ChartRow = {
  date: string;
  close: number;
  revenue?: number;
  ebitda?: number;
  fcf?: number;
};

// Fundamentals are quarterly, price is daily -- attach each fundamental
// period to the nearest trading day on/after it rather than trying to
// force them onto identical x-values, since a period end date is rarely
// itself a trading day.
function mergeForChart(timeseries: CompanyTimeseries): ChartRow[] {
  const rows: ChartRow[] = timeseries.prices.map((p) => ({ date: p.date, close: p.close }));

  for (const f of timeseries.fundamentals) {
    const target = rows.find((row) => row.date >= f.period);
    if (!target) continue;
    if (f.revenue != null) target.revenue = f.revenue;
    if (f.ebitda != null) target.ebitda = f.ebitda;
    if (f.fcf != null) target.fcf = f.fcf;
  }

  return rows;
}

function formatBillions(value: number) {
  return `$${(value / 1e9).toFixed(1)}B`;
}

export default function TimelineChart({ timeseries }: { timeseries: CompanyTimeseries }) {
  const data = mergeForChart(timeseries);

  if (data.length === 0) {
    return <p className="py-12 text-center text-ink/60">No price history ingested yet for this company.</p>;
  }

  return (
    <div className="h-96 w-full font-mono text-xs">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid stroke="var(--color-hairline)" vertical={false} />
          <XAxis dataKey="date" tick={{ fill: "var(--color-ink)" }} minTickGap={40} />
          <YAxis
            yAxisId="price"
            orientation="left"
            tick={{ fill: "var(--color-ink)" }}
            tickFormatter={(v) => `$${v.toFixed(0)}`}
            width={56}
          />
          <YAxis
            yAxisId="fundamentals"
            orientation="right"
            tick={{ fill: "var(--color-ink)" }}
            tickFormatter={formatBillions}
            width={56}
          />
          <Tooltip
            contentStyle={{ background: "var(--color-surface)", border: "1px solid var(--color-hairline)" }}
            labelStyle={{ color: "var(--color-ink)" }}
          />
          <Bar yAxisId="fundamentals" dataKey="revenue" name="Revenue" fill="var(--color-ink)" opacity={0.25} />
          <Line
            yAxisId="fundamentals"
            dataKey="ebitda"
            name="EBITDA"
            stroke="var(--color-gold)"
            dot={false}
            strokeWidth={2}
          />
          <Line yAxisId="fundamentals" dataKey="fcf" name="FCF" stroke="var(--color-up)" dot={false} strokeWidth={2} />
          <Line
            yAxisId="price"
            dataKey="close"
            name="Price"
            stroke="var(--color-accent)"
            dot={false}
            strokeWidth={1.5}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
