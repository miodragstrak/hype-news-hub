import { motion } from "framer-motion";
import { CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { NextStepPanel } from "../components/NextStepPanel";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";
import { cn } from "../lib/utils";

function getFlag(name: string): string {
  if (name.includes("Serbia")) return "🇷🇸";
  if (name.includes("Croatia")) return "🇭🇷";
  if (name.includes("Bosnia") || name.includes("BiH")) return "🇧🇦";
  if (name.includes("Slovenia")) return "🇸🇮";
  if (name.includes("Macedonia")) return "🇲🇰";
  return "🇷🇸";
}

const stages = ["Waiting", "Collecting", "Normalizing", "Creating Stories", "Scoring", "Completed"];

function getStageIndex(isCollecting: boolean, hasCollection: boolean, sourceIndex: number, tick: number): number {
  if (hasCollection) {
    return stages.length - 1;
  }

  if (!isCollecting) {
    return 0;
  }

  const stepped = Math.floor((tick + sourceIndex * 2) / 2) + 1;
  return Math.max(1, Math.min(stages.length - 2, stepped));
}

export function CollectionProgressPage(): JSX.Element {
  const { sources, sourceArticleCounts, collectionResult, isCollecting, collectNow, collectError } = useDemoData();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!isCollecting) {
      setTick(0);
      return;
    }

    const timer = window.setInterval(() => {
      setTick((current) => current + 1);
    }, 900);

    return () => {
      window.clearInterval(timer);
    };
  }, [isCollecting]);

  const safeCounts = useMemo(() => Object.values(sourceArticleCounts), [sourceArticleCounts]);
  const maxArticles = Math.max(...safeCounts, 5);
  const collectedArticles = collectionResult?.articles_total ?? 0;
  const sourcesProcessed = collectionResult?.sources_processed ?? 0;
  const storiesCreated = collectionResult?.stories_total ?? 0;
  const isComplete = Boolean(collectionResult);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-white">Collect Latest News</h2>
        <p className="text-[#c2d3f5]">Gather the latest articles from all connected Hype sources.</p>
        <p className="text-sm text-[#b5c8ed]">Nothing is published without editorial approval.</p>
      </header>

      <Card className="border-[#f5c518]/45 bg-[#0a285f]">
        <CardContent className="flex flex-col gap-4 p-6 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#bcd0f6]">Collection Control</p>
            <p className="mt-2 text-sm text-[#dbe7ff]">Start collection to run intake, normalization, story creation, and scoring.</p>
          </div>
          <Button size="lg" onClick={() => void collectNow()} disabled={isCollecting}>
            {isCollecting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {isCollecting ? "Collecting..." : "Start Collection"}
          </Button>
        </CardContent>
      </Card>

      <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {sources.map((source, index) => {
          const count = sourceArticleCounts[source.name] ?? 5;
          const stageIndex = getStageIndex(isCollecting, isComplete, index, tick);
          const progress = isComplete ? Math.min(100, Math.round((count / maxArticles) * 100)) : isCollecting ? Math.min(98, 8 + stageIndex * 17) : 6;
          const flag = getFlag(source.name);

          return (
            <motion.div
              key={source.name}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.06, duration: 0.4 }}
            >
              <Card className="h-full">
                <CardHeader>
                  <CardTitle className="text-2xl tracking-tight">
                    {flag} {source.name.replace("Hype ", "")}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#b7c9ee]">Current Stage</p>
                    <p className="text-sm font-semibold text-white">{stages[stageIndex]}</p>
                  </div>

                  <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-3">
                    {stages.map((stage, stagePosition) => {
                      const isActive = stagePosition === stageIndex;
                      const isStageComplete = stagePosition < stageIndex || (isComplete && stagePosition === stages.length - 1);

                      return (
                        <div
                          key={stage}
                          className={cn(
                            "flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em]",
                            isStageComplete
                              ? "border-emerald-400/30 bg-emerald-500/15 text-emerald-100"
                              : isActive
                              ? "border-[#f5c518] bg-[#f5c518] text-[#07173d]"
                              : "border-white/20 bg-[#08245a] text-[#b8c9ee]"
                          )}
                        >
                          <span
                            className={cn(
                              "inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px]",
                              isActive ? "bg-[#07173d]/15" : isStageComplete ? "bg-emerald-500/25" : "bg-[#12357a]"
                            )}
                          >
                            {stagePosition + 1}
                          </span>
                          <span>{stage}</span>
                        </div>
                      );
                    })}
                  </div>

                  <div className="h-3 w-full overflow-hidden rounded-full bg-[#12357a]">
                    <motion.div
                      className="h-full rounded-full bg-gradient-to-r from-[#2d67d3] to-[#f5c518]"
                      initial={{ width: "0%" }}
                      animate={{ width: `${progress}%` }}
                      transition={{ duration: 1.1, delay: index * 0.08 }}
                    />
                  </div>

                  <div className="flex items-center justify-between text-sm">
                    <p className="font-medium text-[#dbe6ff]">{count} Articles</p>
                    {progress >= 95 ? (
                      <p className="inline-flex items-center gap-1.5 font-semibold text-emerald-200">
                        <CheckCircle2 className="h-4 w-4" />
                        Completed
                      </p>
                    ) : (
                      <p className="font-semibold text-[#f5c518]">In Progress</p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          );
        })}
      </section>

      {collectError ? (
        <Card className="border-rose-400/40 bg-rose-500/10">
          <CardContent className="p-6 text-sm text-rose-100">Collection error: {collectError}</CardContent>
        </Card>
      ) : null}

      {isComplete ? (
        <Card className="border-emerald-400/35 bg-emerald-500/10">
          <CardContent className="space-y-3 p-6">
            <h3 className="text-2xl font-bold text-emerald-100">Collection Complete</h3>
            <ul className="space-y-1 text-sm text-emerald-50">
              <li>Sources processed: {sourcesProcessed}</li>
              <li>Articles collected: {collectedArticles}</li>
              <li>Stories created: {storiesCreated}</li>
            </ul>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-white/20 bg-[#0a285f]">
          <CardContent className="flex items-center justify-between p-6">
            <p className="text-sm text-[#d8e5ff]">Collection has not started yet.</p>
            <p className="text-4xl font-bold text-[#f5c518]">00</p>
          </CardContent>
        </Card>
      )}

      <NextStepPanel
        message={
          isComplete
            ? "Collection is complete. Continue to processing to merge duplicate articles and create editorial stories."
            : "Start collection using the main action above. Cards will move through waiting, collecting, normalizing, creating stories, and scoring."
        }
        ctaLabel={isComplete ? "Continue to Processing" : "Start Collection"}
        ctaTo={isComplete ? "/process" : undefined}
        disabled={isCollecting || !isComplete}
      />
    </div>
  );
}
