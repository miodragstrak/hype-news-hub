import { NextStepPanel } from "../components/NextStepPanel";
import { Card, CardContent } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";
import { collectionOutcome } from "../lib/collection";

export function ProcessingOverviewPage(): JSX.Element {
  const { collectionResult, isCollecting, collectError, editorialStories, editorialError, isLoadingEditorial } = useDemoData();
  const outcome = collectionOutcome(collectionResult, isCollecting, collectError);
  const hasResults = outcome === "complete" || outcome === "partial";
  const stats = [
    { label: "Articles Collected", value: collectionResult?.articles_total ?? 0 },
    { label: "Articles Grouped into Existing Stories", value: collectionResult?.story_candidates_total ?? 0 },
    { label: "Stories Created", value: collectionResult?.stories_total ?? 0 },
    { label: "Stories in Editorial Queue", value: isLoadingEditorial || editorialError ? "Unavailable" : editorialStories.length },
  ];
  const status = outcome === "running" ? "Collection in progress. Waiting for processing results." :
    outcome === "failed" ? "Latest collection failed." : outcome === "partial" ? "Results available with source failures." :
    hasResults ? "Collection and story grouping completed." : "Run collection to obtain processing results.";

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-white">Process Editorial Pipeline</h2>
        <p className="text-[#c2d3f5]">Normalization, heuristic story matching, and rules-based editorial scoring.</p>
      </header>
      <Card><CardContent className="space-y-3 p-6" role={outcome === "failed" ? "alert" : "status"}>
        <h3 className="text-2xl font-bold">{status}</h3>
        {collectError ? <p>{collectError}</p> : null}
        {collectionResult?.sources_failed ? <p>Sources failed: {collectionResult.sources_failed} of {collectionResult.sources_processed}</p> : null}
        {isCollecting ? <p>Collection counts show the latest available response while the request finishes.</p> :
          collectError && collectionResult ? <p>Collection counts below describe the last received response.</p> : null}
        {editorialError ? <p role="alert">Editorial queue unavailable: {editorialError}</p> :
          isLoadingEditorial ? <p>Loading editorial queue...</p> : <p>Editorial queue loaded: {editorialStories.length} stories.</p>}
      </CardContent></Card>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat) => <Card key={stat.label}><CardContent className="p-5">
          <p className="text-xs uppercase tracking-[0.15em] text-[#b5c8ed]">{stat.label}</p>
          <p className="mt-3 text-4xl font-bold">{stat.value}</p>
        </CardContent></Card>)}
      </div>
      <p className="text-sm text-[#c2d3f5]">Grouped articles represent matching coverage, not verified duplicate removal. AI draft generation and human approval are separate steps.</p>
      <NextStepPanel
        message={editorialStories.length > 0 && !editorialError ? "Inspect original sources in the editorial queue." : "Collect articles and load the editorial queue before reviewing stories."}
        ctaLabel={editorialStories.length > 0 && !editorialError ? "Review Stories" : "Return to Collect"}
        ctaTo={editorialStories.length > 0 && !editorialError ? "/review" : "/"}
        disabled={isCollecting || isLoadingEditorial}
      />
    </section>
  );
}
