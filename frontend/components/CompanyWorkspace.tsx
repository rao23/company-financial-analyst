"use client";

import { useState } from "react";
import TimelineChart from "@/components/TimelineChart";
import InvestigationPanel from "@/components/InvestigationPanel";
import type { CompanyTimeseries } from "@/lib/api";

export default function CompanyWorkspace({ ticker, timeseries }: { ticker: string; timeseries: CompanyTimeseries }) {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  return (
    <>
      <TimelineChart timeseries={timeseries} selectedDate={selectedDate} onDateSelect={setSelectedDate} />
      {selectedDate ? (
        // key forces a remount (fresh Investigation Thread) on every new date click.
        <InvestigationPanel key={selectedDate} ticker={ticker} investigationDate={selectedDate} />
      ) : (
        <p className="border-t hairline pt-4 text-sm text-ink/60">
          Click a point on the chart to ask why the stock moved.
        </p>
      )}
    </>
  );
}
