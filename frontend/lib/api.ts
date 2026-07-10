const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type CompanySearchResult = {
  cik: number;
  ticker: string;
  name: string;
};

export type CompanyDetail = {
  cik: number;
  ticker: string;
  name: string;
  sector: string | null;
  gics: string | null;
  ipo_date: string | null;
  price_coverage_start: string | null;
  has_pre_2009_gap: boolean | null;
};

export type PricePoint = {
  date: string;
  close: number;
};

export type FundamentalPoint = {
  period: string;
  fiscal_year: number | null;
  fiscal_period: string | null;
  revenue: number | null;
  ebitda: number | null;
  fcf: number | null;
};

export type CompanyTimeseries = {
  prices: PricePoint[];
  fundamentals: FundamentalPoint[];
};

async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function searchCompanies(query: string): Promise<CompanySearchResult[]> {
  return apiFetch(`/companies/search?q=${encodeURIComponent(query)}`);
}

export function getCompany(cik: number): Promise<CompanyDetail> {
  return apiFetch(`/companies/${cik}`);
}

export function getCompanyTimeseries(cik: number): Promise<CompanyTimeseries> {
  return apiFetch(`/companies/${cik}/timeseries`);
}
