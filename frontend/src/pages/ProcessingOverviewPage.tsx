import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, Circle, Loader2 } from "lucide-react";
import { Fragment } from "react";
import { Link } from "react-router-dom";

import { NextStepPanel } from "../components/NextStepPanel";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { useDemoData } from "../context/DemoDataContext";

export function ProcessingOverviewPage(): JSX.Element {
  const { collectionResult } = useDemoData();

  const collected = collectionResult?.articles_total ?? 25;
  const duplicatesMerged = Math.max(1, Math.floor(collected * 0.12));
  const uniqueStories = Math.max(collected - duplicatesMerged, 0);
  const readyForReview = Math.max(1, Math.floor(uniqueStories * 0.68));

  const processingStages = [
    { label: "Collected Articles", message: "AI collected articles" },
    { label: "Normalized", message: "AI normalized content" },
    { label: "Stories Created", message: "AI groups related stories..." },
    { label: "Duplicates Merged", message: "AI merges duplicate coverage..." },
    { label: "Editorially Scored", message: "AI evaluates editorial importance..." },
    { label: "Ready for Review", message: "AI prepares the editorial queue..." }
  ];

  const activeStageIndex = collectionResult ? -1 : 0;
  const completedStages = collectionResult ? processingStages.length : 0;

  const stats = [
    { label: "Articles Collected", value: collected },
    { label: "Duplicates Merged", value: duplicatesMerged },
    { label: "Unique Stories", value: uniqueStories },
    { label: "Ready For Review", value: readyForReview }
  ];

  const isProcessingComplete = Boolean(collectionResult);

  return (
    <section className="space-y-7">
      <header className="space-y-2">
        <h2 className="text-4xl font-bold tracking-tight text-white">Process Editorial Signals</h2>
        <p className="text-[#c2d3f5]">Normalize articles, merge duplicates, and rank stories for editorial review.</p>
        <p className="text-sm text-[#b5c8ed]">Actions can be reviewed before publishing.</p>
      </header>

      <Card className="border-white/25 bg-[#0a285f]">
        <CardContent className="space-y-4 p-7">
          <div className="flex gap-3 overflow-x-auto pb-2 lg:grid lg:grid-cols-[repeat(11,max-content)] lg:items-center lg:overflow-visible">
            {processingStages.map((stage, index) => {
              const done = index < completedStages;
              const active = activeStageIndex === index;
              return (
                <Fragment key={stage.label}>
                  <motion.div
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.06, duration: 0.35 }}
                    className={`inline-flex min-w-[190px] items-center gap-2 rounded-2xl border px-4 py-3 ${
                      done
                        ? "border-emerald-400/35 bg-emerald-500/15 text-emerald-50"
                        : active
                        ? "border-[#f5c518] bg-[#f5c518] text-[#07173d]"
                        : "border-white/20 bg-[#08245a] text-[#d4e2ff]"
                    }`}
                  >
                    {done ? (
                      <CheckCircle2 className="h-5 w-5 shrink-0" />
                    ) : active ? (
                      <Loader2 className="h-5 w-5 shrink-0 animate-spin" />
                    ) : (
                      <Circle className="h-5 w-5 shrink-0 text-[#b0c3ea]" />
                    )}
                    <p className="text-sm font-semibold leading-snug">{stage.label}</p>
                  </motion.div>
                  {index < processingStages.length - 1 ? (
                    <ArrowRight className="hidden h-5 w-5 shrink-0 self-center text-[#f5c518] lg:block" />
                  ) : null}
                </Fragment>
              );
            })}
          </div>

          <div className="rounded-2xl border border-white/20 bg-[#08245a] p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#b7c9ee]">
              {isProcessingComplete ? "Completed" : `Step ${activeStageIndex + 1} of ${processingStages.length}`}
            </p>
            <p className="mt-2 text-sm font-semibold text-white">
              {isProcessingComplete ? "AI prepared stories for review." : processingStages[activeStageIndex].message}
            </p>
          </div>
        </CardContent>
      </Card>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat, index) => (
          <motion.div key={stat.label} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.08 }}>
            <Card>
              <CardContent className="p-5">
                <p className="text-xs uppercase tracking-[0.15em] text-[#b5c8ed]">{stat.label}</p>
                <p className="mt-3 text-5xl font-bold text-white">{stat.value}</p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </section>

      {isProcessingComplete ? (
        <Card className="border-emerald-400/35 bg-emerald-500/10">
          <CardContent className="space-y-3 p-6">
            <h3 className="text-2xl font-bold text-emerald-100">Processing Complete</h3>
            <ul className="space-y-1 text-sm text-emerald-50">
              <li>{collected} articles collected</li>
              <li>{duplicatesMerged} duplicates merged</li>
              <li>{uniqueStories} unique stories</li>
              <li>{readyForReview} ready for review</li>
            </ul>
            <Button size="lg" asChild>
              <Link to="/review">Review Editorial Stories</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-white/20 bg-[#0a285f]">
          <CardContent className="p-6 text-sm text-[#d4e2ff]">Run collection first to complete all processing stages.</CardContent>
        </Card>
      )}

      {!isProcessingComplete ? (
        <NextStepPanel
          message="Collection is required before processing can complete. Go back and run Start Collection."
          ctaLabel="Return to Collect"
          ctaTo="/"
        />
      ) : null}
    </section>
  );
}
