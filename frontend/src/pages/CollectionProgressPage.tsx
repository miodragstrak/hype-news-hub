import { CheckCircle2, Loader2 } from "lucide-react";

import { NextStepPanel } from "../components/NextStepPanel";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";
import { collectionOutcome, collectionSources } from "../lib/collection";

export function CollectionProgressPage(): JSX.Element {
  const { sources, sourceError, isLoadingSources, collectionResult, isCollecting, collectNow, collectError, isDemoMode } = useDemoData();
  const outcome = collectionOutcome(collectionResult, isCollecting, collectError);
  const hasUsableResult = outcome === "complete" || outcome === "partial";
  const visibleSources = collectionSources(sources, collectionResult);
  const heading = {
    idle: "Collection has not started yet.",
    running: "Collection in progress.",
    failed: "Collection failed.",
    partial: "Collection completed with source failures.",
    complete: "Collection completed successfully.",
  }[outcome];

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-white">Collect Latest News</h2>
        <p className="text-[#c2d3f5]">Collect articles, normalize content, and group related coverage from Hype sources.</p>
      </header>
      <Card className="border-[#f5c518]/45 bg-[#0a285f]">
        <CardContent className="flex flex-col gap-4 p-6 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#bcd0f6]">Collection Control</p>
            <p className="mt-2 text-sm text-[#dbe7ff]">Source outcomes appear when the collection request finishes.</p>
          </div>
          <Button size="lg" onClick={() => void collectNow()} disabled={isCollecting}>
            {isCollecting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {isCollecting ? "Collecting articles..." : "Start Collection"}
          </Button>
        </CardContent>
      </Card>
      {isLoadingSources ? <p role="status">Checking source discovery...</p> : null}
      {sourceError ? <p role="alert" className="text-rose-100">Source discovery unavailable: {sourceError}</p> : null}
      {!isLoadingSources && !sourceError && visibleSources.length === 0 ? <p>No sources were returned by discovery.</p> : null}
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {visibleSources.map((source) => {
          const result = collectionResult?.source_results?.find((entry) => entry.url === source.url);
          const count = result?.articles_total ?? collectionResult?.articles.filter((article) => article.source_url === source.url).length ?? 0;
          const status = isCollecting ? "Collection or queue refresh in progress" : collectError ? "Latest collection failed" :
            result?.status === "failed" ? "Failed" : result?.status === "success" ? "Collected" :
            collectionResult ? "Per-source outcome unavailable" : "Not collected";
          return (
            <Card key={source.url}>
              <CardHeader><CardTitle>{source.name}</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <p className="break-all text-sm text-[#c2d3f5]">{source.url}</p>
                <p className={result?.status === "failed" ? "text-rose-100" : "text-[#dbe6ff]"}>{status}</p>
                <p>{count} articles{isCollecting && collectionResult ? " in latest response" : ""}</p>
                {result?.error ? <p className="text-sm text-rose-100">{result.error}</p> : null}
              </CardContent>
            </Card>
          );
        })}
      </div>
      <Card className={outcome === "failed" ? "border-rose-400/40" : outcome === "partial" ? "border-amber-400/40" : ""}>
        <CardContent className="space-y-3 p-6" role={outcome === "failed" ? "alert" : "status"}>
          <h3 className="text-2xl font-bold">{heading}</h3>
          {collectError ? <p className="text-rose-100">{collectError}</p> : null}
          {isCollecting ? <p>Waiting for collection and editorial queue results. Counts show the latest available response.</p> :
            collectError && collectionResult ? <p>Counts below describe the last received collection response.</p> : null}
          {collectionResult ? (
            <ul className="space-y-1 text-sm">
              <li>Sources processed: {collectionResult.sources_processed}</li>
              <li>Sources failed: {collectionResult.sources_failed}</li>
              <li>Articles collected: {collectionResult.articles_total}</li>
              <li>Available stories: {collectionResult.stories_total}</li>
            </ul>
          ) : null}
          {hasUsableResult ? <p className="inline-flex items-center gap-2 text-sm"><CheckCircle2 className="h-4 w-4" />{isDemoMode ? "Sample results available." : "Collection results available."}</p> : null}
        </CardContent>
      </Card>
      <NextStepPanel
        message={hasUsableResult ? "Inspect the returned story grouping and editorial queue." : "Start collection to retrieve current source results."}
        ctaLabel={hasUsableResult ? "View Processing Results" : "Start Collection"}
        ctaTo={hasUsableResult ? "/process" : undefined}
        onAction={hasUsableResult ? undefined : () => void collectNow()}
        disabled={isCollecting}
      />
    </section>
  );
}
