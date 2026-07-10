"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { searchCompanies, type CompanySearchResult } from "@/lib/api";

const DEBOUNCE_MS = 200;

export default function SearchBox() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CompanySearchResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    const trimmed = query.trim();
    if (trimmed.length === 0) return; // cleared synchronously in handleQueryChange below

    debounceRef.current = setTimeout(async () => {
      try {
        const matches = await searchCompanies(trimmed);
        setResults(matches);
        setIsOpen(true);
      } catch {
        setResults([]);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  function goToCompany(cik: number) {
    setIsOpen(false);
    setQuery("");
    router.push(`/company/${cik}`);
  }

  function handleQueryChange(value: string) {
    setQuery(value);
    if (value.trim().length === 0) {
      setResults([]);
      setIsOpen(false);
    }
  }

  return (
    <div className="relative w-full max-w-xl">
      <input
        type="text"
        value={query}
        onChange={(e) => handleQueryChange(e.target.value)}
        onFocus={() => results.length > 0 && setIsOpen(true)}
        onBlur={() => setTimeout(() => setIsOpen(false), 100)}
        placeholder="Search by ticker, company name, or alias"
        className="w-full border-b hairline bg-transparent px-1 py-3 text-lg font-sans text-ink placeholder:text-ink/40 focus:outline-none focus:border-accent"
      />
      {isOpen && results.length > 0 && (
        <ul className="absolute left-0 right-0 top-full z-10 mt-1 max-h-80 overflow-auto border hairline bg-surface shadow-sm">
          {results.map((result) => (
            <li key={result.cik}>
              <button
                type="button"
                onMouseDown={() => goToCompany(result.cik)}
                className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left hover:bg-paper"
              >
                <span className="font-sans text-ink">{result.name}</span>
                <span className="font-mono text-sm text-accent">{result.ticker}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
