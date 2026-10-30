import { useDemoData } from "../context/DemoDataContext";

export function DataStatusBanner(): JSX.Element | null {
  const { isDemoMode, sourceError, storiesError, editorialError, collectError, isCollecting, collectionResult } = useDemoData();
  const errors = [sourceError, storiesError, editorialError, collectError ? `Latest collection: ${collectError}` : null].filter(Boolean);
  const hasSourceFailures = !isCollecting && (collectionResult?.sources_failed ?? 0) > 0;
  if (!isDemoMode && !isCollecting && !hasSourceFailures && errors.length === 0) return null;

  return (
    <div className="space-y-3">
      {isDemoMode ? (
        <div role="status" className="rounded-2xl border border-amber-400/40 bg-[#332c13] p-4 text-sm text-amber-50">
          Demo mode — sample stories and simulated collection. No live news is collected.
        </div>
      ) : null}
      {isCollecting ? (
        <p role="status" className="rounded-2xl border border-white/20 bg-[#08245a] p-4 text-sm text-white">
          Collection is running. Displayed data reflects the latest available response.
        </p>
      ) : hasSourceFailures ? (
        <p role="status" className="rounded-2xl border border-amber-400/40 bg-[#332c13] p-4 text-sm text-amber-50">
          Last collection response: {collectionResult?.sources_failed} of {collectionResult?.sources_processed} sources failed.
        </p>
      ) : null}
      {errors.length > 0 ? (
        <div role="alert" className="rounded-2xl border border-rose-400/40 bg-[#3a162b] p-4 text-sm text-rose-50">
          <p className="font-semibold">Some newsroom data could not be loaded.</p>
          <ul className="mt-2 list-inside list-disc">
            {errors.map((error, index) => <li key={index}>{error}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
