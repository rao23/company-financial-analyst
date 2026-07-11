import { notFound } from "next/navigation";
import CompanyHeader from "@/components/CompanyHeader";
import CompanyWorkspace from "@/components/CompanyWorkspace";
import { getCompany, getCompanyTimeseries } from "@/lib/api";

export default async function CompanyPage({ params }: { params: Promise<{ cik: string }> }) {
  const { cik } = await params;
  const cikNumber = Number(cik);
  if (!Number.isInteger(cikNumber)) notFound();

  let company;
  let timeseries;
  try {
    [company, timeseries] = await Promise.all([getCompany(cikNumber), getCompanyTimeseries(cikNumber)]);
  } catch {
    notFound();
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-10">
      <CompanyHeader company={company} />
      <CompanyWorkspace ticker={company.ticker} timeseries={timeseries} />
    </main>
  );
}
