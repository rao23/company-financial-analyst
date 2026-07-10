import SearchBox from "@/components/SearchBox";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-6">
      <div className="flex w-full max-w-xl flex-col items-center gap-6">
        <h1 className="font-display text-4xl italic text-ink">Earnings Timeline AI</h1>
        <p className="text-center text-ink/70">
          Search a company to see fundamentals plotted against price, and ask why it moved.
        </p>
        <SearchBox />
      </div>
    </main>
  );
}
